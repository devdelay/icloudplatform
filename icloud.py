"""
homeassistant.components.icloud
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Platform that supports scanning iCloud.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/icloud/
"""
import logging
import time as time

import re
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_NAME
from homeassistant.helpers.entity import Entity
from homeassistant.components.device_tracker import see
from homeassistant.helpers.event import track_state_change
from homeassistant.helpers.event import track_time_change
from homeassistant.helpers.event import track_point_in_time
from homeassistant.helpers.event import track_utc_time_change
import homeassistant.util.dt as dt_util
from homeassistant.util.location import distance

_LOGGER = logging.getLogger(__name__)

REQUIREMENTS = ['pyicloud==0.7.2']

DEPENDENCIES = ['zone', 'device_tracker']

CONF_INTERVAL = 'interval'
DEFAULT_INTERVAL = 8

# entity attributes
ATTR_ACCOUNTNAME = 'accountname'
ATTR_INTERVAL = 'interval'
ATTR_DEVICENAME = 'devicename'
ATTR_BATTERY = 'battery'
ATTR_DISTANCE = 'distance'

ICLOUDTRACKERS = {}

DOMAIN = 'icloud'
DOMAIN2 = 'idevice'


def setup(hass, config):
    """ Set up the iCloud Scanner. """
    
    if config.get(DOMAIN) is None:
        return False

    for account, account_config in config[DOMAIN].items():

        if not isinstance(account_config, dict):
            _LOGGER.error("Missing configuration data for account %s", account)
            continue

        if CONF_USERNAME not in account_config:
            _LOGGER.error("Missing username for account %s", account)
            continue
        
        if CONF_PASSWORD not in account_config:
            _LOGGER.error("Missing password for account %s", account)
            continue
        
        # Get the username and password from the configuration
        username = account_config.get(CONF_USERNAME)
        password = account_config.get(CONF_PASSWORD)
        
        ignored_devices = []
        if 'ignored_devices' in account_config:
            ignored_dev = account_config.get('ignored_devices')
            for each_dev in ignored_dev:
                ignored_devices.append(each_dev)
        _LOGGER.info("icloud %s ignored_devices %s", account, ignored_devices)
        
        icloudaccount = Icloud(hass, username, password, account,
                               ignored_devices)
        icloudaccount.entity_id = DOMAIN + '.' + account
        icloudaccount.update_ha_state()
        _LOGGER.info("icloud %s toegevoegd", account)
        ICLOUDTRACKERS[account] = icloudaccount
        if ICLOUDTRACKERS[account].api is not None:
            for device in ICLOUDTRACKERS[account].devices:
                iclouddevice = ICLOUDTRACKERS[account].devices[device]
                devicename = iclouddevice.devicename.lower()
                _LOGGER.info("icloud %s device %s monitoren", account, devicename)
                track_state_change(hass,
                                   'device_tracker.' + devicename,
                                   iclouddevice.devicechanged)
                                   
        if 'manual_update' in account_config:
            def update_now(now):
                ICLOUDTRACKERS[accountname].update_icloud(see)
                _LOGGER.info("icloud %s device update_now called", account)
            
            manual_update = account_config.get('manual_update')
            for each_time in manual_update:
                _LOGGER.info("icloud %s device manueel updaten om %s", account, each_time)
                each_time = dt_util.parse_time_str(each_time)
                track_time_change(hass, update_now,
                                  hour=each_time.hour,
                                  minute=each_time.minute,
                                  second=each_time.second)
        
    if not ICLOUDTRACKERS:
        _LOGGER.error("No ICLOUDTRACKERS added")
        return False
        
    def lost_iphone(call):
        """ Calls the lost iphone function if the device is found """
        accountname = call.data.get('accountname')
        devicename = call.data.get('devicename')
        _LOGGER.info("icloud %s device %s lost iphone called", accountname, devicename)
        if accountname in ICLOUDTRACKERS:
            _LOGGER.info("icloud %s device %s lost iphone uitvoeren", accountname, devicename)
            ICLOUDTRACKERS[accountname].lost_iphone(devicename)

    hass.services.register(DOMAIN, 'lost_iphone',
                           lost_iphone)
                           
    def update_icloud(call):
        """ Calls the update function of an icloud account """
        accountname = call.data.get('accountname')
        devicename = call.data.get('devicename')
        _LOGGER.info("icloud %s device %s update icloud called", accountname, devicename)
        if accountname in ICLOUDTRACKERS:
            _LOGGER.info("icloud %s device %s update icloud uitvoeren", accountname, devicename)
            ICLOUDTRACKERS[accountname].update_icloud(see, devicename)
    hass.services.register(DOMAIN,
                           'update_icloud', update_icloud)
            
    def keep_alive(now):
        """ Keeps the api logged in of all account """
        _LOGGER.info("icloud keep alive called")
        for accountname in ICLOUDTRACKERS:
            _LOGGER.info("icloud %s keep alive uitvoeren", accountname)
            ICLOUDTRACKERS[accountname].keep_alive()
            
    track_utc_time_change(
        hass, keep_alive,
        second=0
    )
    
    def setinterval(call):
        """ Calls the update function of an icloud account """
        accountname = call.data.get('accountname')
        interval = call.data.get('interval')
        _LOGGER.info("icloud %s interval %s set interval called", accountname, interval)
        if accountname in ICLOUDTRACKERS:
            _LOGGER.info("icloud %s interval %s set interval uitvoeren", accountname, interval)
            ICLOUDTRACKERS[accountname].setinterval(interval)

    hass.services.register(DOMAIN,
                           'setinterval', setinterval)

    # Tells the bootstrapper that the component was successfully initialized
    return True

class IDevice(Entity):  # pylint: disable=too-many-instance-attributes
    """ Represents a Proximity in Home Assistant. """
    def __init__(self, hass, icloudobject, name):
        # pylint: disable=too-many-arguments
        self.hass = hass
        self.icloudobject = icloudobject
        self.devicename = name
        self._max_wait_seconds = 120
        self._request_interval_seconds = 10
        self._interval = 1
        self.api = icloudobject.api
        self._distance = None
        self._battery = None
        self._updating = False
        self._overridestate = None
        
    @property
    def state(self):
        """ returns the state of the icloud tracker """
        return self._interval
        
    @property
    def unit_of_measurement(self):
        """ Unit of measurement of this entity """
        return "minutes"

    @property
    def state_attributes(self):
        """ returns the friendlyname of the icloud tracker """
        return {
            ATTR_DEVICENAME: self.devicename,
            ATTR_BATTERY: self._battery,
            ATTR_DISTANCE: self._distance
        }
        
    def keep_alive(self):
        """ Keeps the api alive """
        _LOGGER.info("iclouddevice %s keep alive called", self.devicename)
        currentminutes = dt_util.now().hour * 60 + dt_util.now().minute
        if currentminutes % self._interval == 0:
            self.update_icloud(see)

    def lost_iphone(self):
        """ Calls the lost iphone function if the device is found """
        _LOGGER.info("iclouddevice %s lost iphone called", self.devicename)
        if self.api is not None:
            self.api.authenticate()
            for device in self.api.devices:
                status = device.status()
                dev_id = re.sub(r"(\s|\W|')", '', status['name']).lower()
                if self.devicename == dev_id:
                    device.play_sound()

    def data_is_accurate(self, data):
        if not data:
            _LOGGER.info("iclouddevice %s location no data", self.devicename)
            return False
        elif not data['locationFinished']:
            _LOGGER.info("iclouddevice %s location not finished", self.devicename)
            return False
        # elif data['isInaccurate']:
        #     return False
        # elif data['isOld']:
        #     return False
        # elif data['horizontalAccuracy'] > self._min_horizontal_accuracy:
        #    return False
        _LOGGER.info("iclouddevice %s location accurate", self.devicename)
        return True

    def update_icloud(self, see):
        """ Authenticate against iCloud and scan for devices. """        
        _LOGGER.info("iclouddevice %s update icloud called", self.devicename)
        if self._updating:
            _LOGGER.info("iclouddevice %s already updating", self.devicename)
            return

        if self.api is not None:
            from pyicloud.exceptions import PyiCloudNoDevicesException

            try:
                # The session timeouts if we are not using it so we
                # have to re-authenticate. This will send an email.
                self.api.authenticate()
                _LOGGER.info("iclouddevice %s api authenticated", self.devicename)
                # Loop through every device registered with the iCloud account
                for device in self.api.devices:
                    status = device.status()
                    dev_id = re.sub(r"(\s|\W|')", '', status['name']).lower()
                    if self.devicename == dev_id:
                        _LOGGER.info("iclouddevice %s start updating location", self.devicename)
                        maxseconds = self._max_wait_seconds
                        if self._interval == 1:
                            maxseconds = 30
                        started = time.time()
                        while time.time() - started < maxseconds:
                            self._updating = True
                            location = device.location()
                            if not location or self.data_is_accurate(location):
                                break
                            time.sleep(self._request_interval_seconds)
                        self._updating = False
                        if location:
                            _LOGGER.info("iclouddevice %s update device tracker", self.devicename)
                            see(
                                hass=self.hass,
                                dev_id=dev_id,
                                host_name=status['name'],
                                gps=(location['latitude'],
                                     location['longitude']),
                                battery=status['batteryLevel']*100,
                                gps_accuracy=location['horizontalAccuracy']
                            )
                        break
            except PyiCloudNoDevicesException:
                _LOGGER.info('No iCloud Devices found!')
                
    def get_default_interval(self):
        devid = 'device_tracker.' + self.devicename
        devicestate = self.hass.states.get(devid)
        self.devicechanged(self.devicename, None, devicestate)
                
    def setinterval(self, interval=None):
        _LOGGER.info('iclouddevice %s: old interval %d',
                     self.devicename, self._interval)
        if interval is not None:
            devid = 'device_tracker.' + self.devicename
            devicestate = self.hass.states.get(devid)
            self._overridestate = devicestate.state
            self._interval = interval
        else:
            self.get_default_interval()
        self.update_ha_state()
        _LOGGER.info('iclouddevice %s: new interval %d',
                     self.devicename, self._interval)
        update_icloud(see)
      
    def devicechanged(self, entity, old_state, new_state):
        if entity is None:
            return
            
        _LOGGER.info('iclouddevice %s: state %s', self.devicename, new_state.state)
        self._distance = None
        if 'latitude' in new_state.attributes:
            device_state_lat = new_state.attributes['latitude']
            device_state_long = new_state.attributes['longitude']
            zone_state = self.hass.states.get('zone.home')
            zone_state_lat = zone_state.attributes['latitude']
            zone_state_long = zone_state.attributes['longitude']
            self._distance = distance(device_state_lat, device_state_long,
                                      zone_state_lat, zone_state_long)
            self._distance = round(self._distance / 1000, 1)
        self._battery = None
        if 'battery' in new_state.attributes:
            self._battery = new_state.attributes['battery']
            
        if new_state.state == self._overridestate:
            self.update_ha_state()
            return
            
        self._overridestate = None
        
        if new_state.state != 'not_home':
            self._interval = 30
            _LOGGER.info('iclouddevice %s: state %s',
                         self.devicename, new_state.state)
            self.update_ha_state()
        else:
            if self._distance is None:
                self.update_ha_state()
                return
            _LOGGER.info('iclouddevice %s: distance %d',
                         self.devicename, self._distance)
            if self._distance > 50:
                self._interval = 30
            elif self._distance > 25:
                self._interval = 15
            elif self._distance > 10:
                self._interval = 5
            else:
                self._interval = 1
            if self._battery is not None:
                if self._battery <= 33 and self._distance > 3:
                    self._interval = self._interval * 2
                _LOGGER.info('iclouddevice %s: battery %d',
                             self.devicename, self._battery)
            self.update_ha_state()
        _LOGGER.info('iclouddevice %s: new interval %d',
                     self.devicename, self._interval)


class Icloud(Entity):  # pylint: disable=too-many-instance-attributes
    """ Represents a Proximity in Home Assistant. """
    def __init__(self, hass, username, password, name, ignored_devices):
        # pylint: disable=too-many-arguments
        from pyicloud import PyiCloudService
        from pyicloud.exceptions import PyiCloudFailedLoginException

        self.hass = hass
        self.username = username
        self.password = password
        self.accountname = name
        self._max_wait_seconds = 120
        self._request_interval_seconds = 10
        self._interval = 1
        self.api = None
        self.devices = {}
        self._ignored_devices = ignored_devices

        if self.username is None or self.password is None:
            _LOGGER.error('Must specify a username and password')
        else:
            try:
                _LOGGER.info('Logging into iCloud Account')
                # Attempt the login to iCloud
                self.api = PyiCloudService(self.username,
                                           self.password,
                                           verify=True)
                for device in self.api.devices:
                    status = device.status()
                    devicename = re.sub(r"(\s|\W|')", '',
                                        status['name']).lower()
                    _LOGGER.info("icloud %s device %s ignored_devices %s", self.accountname, devicename, self._ignored_devices)
                    if (devicename not in self.devices and
                        devicename not in self._ignored_devices):
                        idevice = IDevice(self.hass, self, devicename)
                        idevice.entity_id = DOMAIN2 + '.' + devicename
                        idevice.update_ha_state()
                        self.devices[devicename] = idevice
                _LOGGER.info("icloud %s devices %s ignored_devices %s", self.accountname, self.devices, self._ignored_devices)
            except PyiCloudFailedLoginException as error:
                _LOGGER.exception('Error logging into iCloud Service: %s',
                                  error)

    @property
    def state(self):
        """ returns the state of the icloud tracker """
        return self.api is not None

    @property
    def state_attributes(self):
        """ returns the friendlyname of the icloud tracker """
        return {
            ATTR_ACCOUNTNAME: self.accountname
        }
        
    def keep_alive(self):
        """ Keeps the api alive """
        _LOGGER.info("icloud %s keep alive called", self.accountname)
        if self.api is not None:
            self.api.authenticate()
            for device in self.api.devices:
                status = device.status()
                devicename = re.sub(r"(\s|\W|')", '', status['name']).lower()
                if devicename not in self._ignored_devices:
                    if devicename not in self.devices:
                        idevice = IDevice(self.hass, self, devicename)
                        idevice.entity_id = DOMAIN2 + '.' + devicename
                        idevice.update_ha_state()
                        self.devices[devicename] = idevice
                    self.devices[devicename].keep_alive()

    def lost_iphone(self, devicename):
        """ Calls the lost iphone function if the device is found """
        _LOGGER.info("icloud %s keep alive called for device", self.accountname, devicename)
        if self.api is not None:
            self.api.authenticate()
            for device in self.api.devices:
                status = device.status()
                devname = re.sub(r"(\s|\W|')", '', status['name']).lower()
                if (devicename is not None and
                    devicename not in self._ignored_devices):
                    return
                if devname not in self.devices:
                    idevice = IDevice(self.hass, self, devname)
                    idevice.entity_id = DOMAIN2 + '.' + devname
                    idevice.update_ha_state()
                    self.devices[devname] = idevice
                if devicename is None or devicename == devname:
                    self.devices[devname].play_sound()

    def update_icloud(self, see, devicename=None):
        """ Authenticate against iCloud and scan for devices. """
        _LOGGER.info("icloud %s update icloud called for device %s", self.accountname, devicename)
        if self.api is not None:
            from pyicloud.exceptions import PyiCloudNoDevicesException

            try:
                # The session timeouts if we are not using it so we
                # have to re-authenticate. This will send an email.
                self.api.authenticate()
                # Loop through every device registered with the iCloud account
                for device in self.api.devices:
                    status = device.status()
                    devname = re.sub(r"(\s|\W|')", '', status['name']).lower()
                    if (devname not in self.devices and
                        devicename not in self._ignored_devices):
                        idevice = IDevice(self.hass, self, devname)
                        idevice.entity_id = DOMAIN2 + '.' + devname
                        idevice.update_ha_state()
                        self.devices[devname] = idevice
                    if devicename is None or devicename == devname:
                        self.devices[devname].update_icloud(see)
            except PyiCloudNoDevicesException:
                _LOGGER.info('No iCloud Devices found!')
                
    def setinterval(self, interval=None, devicename=None):
        _LOGGER.info("icloud %s set interval called for devicename %s with interval %d", self.accountname, devicename, interval)
        if devicename is None:
            for device in self.devices:
                device.setinterval(interval)
                device.update_icloud(see)
        elif devicename in self.devices:
            self.devices[devicename] = setinterval(interval)
            self.devices[devicename].update_icloud(see)
