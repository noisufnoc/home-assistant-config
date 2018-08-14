"""
Sensor from a Splunk query.
"""

"""
The splunk sensor platform collect values from a Splunk query to populate sensor state (and attributes). This can also be used to present statistics about Home Assistant sensors if used with the recorder component.

To configure this sensor, define the Splunk instance connection variables and a list of queries in configuration.yaml file. A sensor will be created for each query.

# Full example configuration.yaml
sensor:
  - platform: splunk
    host: hostname.domain
    port: 8089
    ssl: True
    verify_ssl: False
    timeout: 30
    username: hassuser
    password: 'password'
    scan_interval: 30
    queries:
      - name: Disk Free
        query: 'index=_introspection sourcetype=splunk_disk_objects component=Partitions | rename data.available AS disk_available | rename data.capacity AS disk_capacity | rename data.mount_point AS mount_point | rename data.fs_type AS fs_type | eval perc_free = round((disk_capacity/disk_available)*100,2) | table perc_free mount_point fs_type'
        earliest_time: '-15m'
        latest_time: 'now'
        field: 'perc_free'
        unit_of_measurement: 'percentage'
        attributes:
          - mount_point
          - fs_type

CONFIGURATION VARIABLES

host
    (Required) (string): The hostname or IP address of the Splunk instance.

port
    (Optional) (integer): The port to use when connecting to the splunkd service of Splunk. Defaults to '8089'.

ssl
    (Optional) (boolean): Use SSL when connecting to the Splunk instance. Defaults to 'True'

verify_ssl
    (Optional) (boolean): Verify the SSL certificate of the Splunk instance. Defaults to 'True'

timeout
    (Optional) (integer): The number of seconds to wait for a response before aborting. Defaults to '10'.

username
    (Required) (string): The username for accessing the Splunk instance.

password
    (Required) (string): The password for accessing the Splunk instance.

scan_interval
    (Optional) (integer): The number of seconds for polling the Splunk instance.

queries
    (Required) (map):

    name
        (Required) (string): The name of the sensor.
    query
        (Requried) (string): A Splunk query string. The results should be limited to 1 event. If more than 1 event is returned, only the first result will be processed. The results MUST be formatted in Splunk using the 'table' command.
    earliest_time
        (Optional) (string): The time modifier to specify the earliest time for the time range of the search. Defaults to '-60m@m'
    latest_time
        (Optional) (string): The time modifier to specify the latest time for the time range of the search. Defaults to 'now'"
    field
        (Requried) (string): The field name of the value that represents the state of the sensor.
    unit_of_measurement
        (Optional) (string): Defines the units of measurement of the sensor, if any.
    attributes
        (Optional) (list | string): A list of fields to extract values and set as sensor attributes.
"""

import logging
from datetime import timedelta
import json

import voluptuous as vol
import requests

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_HOST, CONF_PORT, CONF_SSL, CONF_VERIFY_SSL, CONF_TIMEOUT,
    CONF_USERNAME, CONF_PASSWORD, CONF_API_KEY, CONF_SCAN_INTERVAL,
    CONF_NAME, CONF_UNIT_OF_MEASUREMENT
)
from homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

CONF_QUERIES = 'queries'
CONF_QUERY = 'query'
CONF_EARLIEST_TIME = 'earliest_time'
CONF_LATEST_TIME = 'latest_time'
CONF_FIELD = 'field'
CONF_ATTRIBUTES = 'attributes'

DEFAULT_PORT = 8089
DEFAULT_SSL = True
DEFAULT_VERIFY_SSL = True
DEFAULT_TIMEOUT = 10
DEFAULT_SCAN_INTERVAL = timedelta(seconds=300)
DEFAULT_EARLIEST_TIME = '-60m@m'
DEFAULT_LATEST_TIME = 'now'

def validate_splunk_query(query_string):
    """ Ensure that the Splunk query is valid. """
    return query_string

_QUERY_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_QUERY): vol.All(cv.string, validate_splunk_query),
    vol.Optional(CONF_EARLIEST_TIME, default=DEFAULT_EARLIEST_TIME): cv.string,
    vol.Optional(CONF_LATEST_TIME, default=DEFAULT_LATEST_TIME): cv.string,
    vol.Required(CONF_FIELD): cv.string,
    vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
    vol.Optional(CONF_ATTRIBUTES, default=[]): cv.ensure_list_csv,
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_SSL, default=DEFAULT_SSL): cv.boolean,
    vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_API_KEY): cv.string,
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    vol.Required(CONF_QUERIES): [_QUERY_SCHEMA],
})

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Splunk sensor."""

    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    ssl = config.get(CONF_SSL)
    verify_ssl = config.get(CONF_VERIFY_SSL)
    timeout = config.get(CONF_TIMEOUT)
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    api_key = config.get(CONF_API_KEY)
    scan_interval = config.get(CONF_SCAN_INTERVAL)

    base_url = 'http{}://{}:{}'.format('s' if ssl else '', host, port)

    if not api_key:
        r = requests.get(base_url + '/services/auth/login', data={'username':username, 'password':password, 'output_mode':'json'}, timeout=timeout, verify=verify_ssl)
        r.raise_for_status()
        api_key = json.loads(r.text)['sessionKey']

    # should probably test the api_key here

    splunk_conf = {
        'base_url': base_url,
        'api_key': api_key,
        'verify_ssl': verify_ssl,
        'timeout': timeout
    }

    splunk_queries = []

    for query in config.get(CONF_QUERIES):
        query_name = query.get(CONF_NAME)
        query_string = query.get(CONF_QUERY)
        query_earliest = query.get(CONF_EARLIEST_TIME)
        query_latest = query.get(CONF_LATEST_TIME)
        query_field = query.get(CONF_FIELD)
        query_unit = query.get(CONF_UNIT_OF_MEASUREMENT)
        query_attributes = query.get(CONF_ATTRIBUTES)

        query_conf = {
            'query_name': query_name,
            'query_string': query_string,
            'query_earliest': query_earliest,
            'query_latest': query_latest,
            'query_field': query_field,
            'query_unit': query_unit,
            'query_attributes': query_attributes
        }

        splunk_queries.append(SplunkSensor(hass, splunk_conf, query_conf))

    add_devices(splunk_queries, True)

class SplunkSensor(Entity):
    """Implementation of a Splunk sensor."""

    def __init__(self, hass, splunk_conf, query_conf):
        """Initialize the Splunk sensor."""
        self._base_url = splunk_conf['base_url']
        self._api_key = splunk_conf['api_key']
        self._verify_ssl = splunk_conf['verify_ssl']
        self._timeout = splunk_conf['timeout']
        self._name = query_conf['query_name']
        self._query = query_conf['query_string']
        self._query_earliest = query_conf['query_earliest']
        self._query_latest = query_conf['query_latest']
        self._field = query_conf['query_field']
        self._unit_of_measurement = query_conf['query_unit']
        self._query_attributes = query_conf['query_attributes']
        self._attributes = None
        self._state = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._attributes

    def update(self):
        """Get the latest data from Splunk REST API and update the state."""

        try:
            r = requests.post(self._base_url + '/services/search/jobs', headers={ 'Authorization': ('Splunk %s' %self._api_key)}, data={'search':'search ' + self._query, 'earliest_time':self._query_earliest, 'latest_time':self._query_latest, 'output_mode':'json', 'exec_mode':'oneshot'}, timeout=self._timeout, verify=self._verify_ssl)
            r.raise_for_status()

            if len(json.loads(r.text)['results']) < 1:
                _LOGGER.warning("%s returned no results.", self._name)
                self._state = None
                return
            else:
                results = json.loads(r.text)['results'][0]

        except requests.exceptions.RequestException as ex:
            _LOGGER.error("Error executing Splunk query: %s", ex)
            return

        if self._field in results:
            value = results[self._field]

            if self._query_attributes:
                self._attributes = {}

                for k in self._query_attributes:
                    if k in results:
                        att = results[k]
                        _LOGGER.debug("SPLUNK | attributes: %s", att)

                attrs = {k: results[k] for k in self._query_attributes
                        if k in results}

                self._attributes = attrs

        else:
            value = None

        if value is None:
            value = STATE_UNKNOWN

        self._state = value
