# WeatherFlow PiConsole: Raspberry Pi Python console for WeatherFlow Tempest
# and Smart Home Weather stations.
# Copyright (C) 2018-2021 Peter Davis

# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.

# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

# You should have received a copy of the GNU General Public License along with
# this program. If not, see <http://www.gnu.org/licenses/>.

# ==============================================================================
# DEFINE GOBAL VARIABLES
# ==============================================================================
SHUTDOWN = 0
REBOOT = 0

# ==============================================================================
# CREATE OR UPDATE wfpiconsole.ini FILE
# ==============================================================================
# Import required modules
from lib     import config as configFile
from pathlib import Path

# Create or update config file if required
if not Path('wfpiconsole.ini').is_file():
    configFile.create()
else:
    configFile.update()

# ==============================================================================
# INITIALISE KIVY GRAPHICS WINDOW BASED ON CURRENT HARDWARE TYPE
# ==============================================================================
# Import required modules
import configparser
import os

# Load wfpiconsole.ini config file
config = configparser.ConfigParser()
config.read('wfpiconsole.ini')

# Initialise Kivy backend based on current hardware
if config['System']['Hardware'] in ['Pi4','Linux']:
    os.environ['SDL_VIDEO_ALLOW_SCREENSAVER'] = '1'
    os.environ['KIVY_GRAPHICS'] = 'gles'
    os.environ['KIVY_WINDOW']   = 'sdl2'
elif config['System']['Hardware'] in ['PiB','Pi3']:
    os.environ['KIVY_GL_BACKEND'] = 'gl'

# ==============================================================================
# INITIALISE KIVY WINDOW PROPERTIES BASED ON OPTIONS SET IN wfpiconsole.ini
# ==============================================================================
# Import required modules
from kivy.config import Config as kivyconfig

# Generate default wfpiconsole Kivy config file. Config file is always
# regenerated to ensure changes to the default file are always copied across
defaultconfig = configparser.ConfigParser()
defaultconfig.read(os.path.expanduser('~/.kivy/') + 'config.ini')
with open(os.path.expanduser('~/.kivy/') + 'config_wfpiconsole.ini','w') as cfg:
    defaultconfig.write(cfg)

# Load wfpiconsole Kivy configuration file
kivyconfig.read(os.path.expanduser('~/.kivy/') + 'config_wfpiconsole.ini')

# Set Kivy window properties
if config['System']['Hardware'] in ['Pi4', 'Linux', 'Other']:
    kivyconfig.set('graphics', 'minimum_width',  '800')
    kivyconfig.set('graphics', 'minimum_height', '480')
    if int(config['Display']['Fullscreen']):
        kivyconfig.set('graphics', 'fullscreen', 'auto')
    else:
        kivyconfig.set('graphics', 'fullscreen', '0')
        kivyconfig.set('graphics', 'width',  config['Display']['Width'])
        kivyconfig.set('graphics', 'height', config['Display']['Height'])
    if int(config['Display']['Border']):
        kivyconfig.set('graphics', 'borderless', '0')
    else:
        kivyconfig.set('graphics', 'borderless', '1')

# ==============================================================================
# INITIALISE MOUSE SUPPORT IF OPTION SET in wfpiconsole.ini
# ==============================================================================
# Enable mouse support on Raspberry Pi 3 if not already set
if config['System']['Hardware'] in ['PiB','Pi3']:
    if not config.has_option('modules','cursor'):
        kivyconfig.set('modules','cursor','1')

# Initialise mouse support if required
if int(config['Display']['Cursor']):
    kivyconfig.set('graphics', 'show_cursor', '1')
else:
    kivyconfig.set('graphics', 'show_cursor', '0')

# Save wfpiconsole Kivy configuration file
kivyconfig.write()

# ==============================================================================
# IMPORT REQUIRED CORE KIVY MODULES
# ==============================================================================
from kivy.properties         import ConfigParserProperty, StringProperty
from kivy.properties         import DictProperty, NumericProperty
from kivy.core.window        import Window
from kivy.factory            import Factory
from kivy.clock              import Clock
from kivy.lang               import Builder
from kivy.app                import App

# ==============================================================================
# IMPORT REQUIRED LIBRARY MODULES
# ==============================================================================
from lib import astronomical      as astro
from lib import settings          as userSettings
from lib import sager             as sagerForecast
from lib import properties
from lib import forecast
from lib import status
from lib import system
from lib import config

# ==============================================================================
# IMPORT REQUIRED SERVICEs
# ==============================================================================
from service.websocket import websocketClient

# ==============================================================================
# IMPORT REQUIRED PANELS
# ==============================================================================
from panels.temperature import TemperaturePanel,   TemperatureButton
from panels.barometer   import BarometerPanel,     BarometerButton
from panels.lightning   import LightningPanel,     LightningButton
from panels.wind        import WindSpeedPanel,     WindSpeedButton
from panels.forecast    import ForecastPanel,      ForecastButton
from panels.forecast    import SagerPanel,         SagerButton
from panels.rainfall    import RainfallPanel,      RainfallButton
from panels.astro       import SunriseSunsetPanel, SunriseSunsetButton
from panels.astro       import MoonPhasePanel,     MoonPhaseButton
from panels.menu        import mainMenu

# ==============================================================================
# IMPORT CUSTOM USER PANELS
# ==============================================================================
if Path('user/customPanels.py').is_file():
    from user.customPanels import *

# ==============================================================================
# IMPORT REQUIRED SYSTEM MODULES
# ==============================================================================
from oscpy.server  import OSCThreadServer
from oscpy.client  import OSCClient
from functools     import partial
import subprocess
import threading
import json

# ==============================================================================
# IMPORT REQUIRED KIVY GRAPHICAL AND SETTINGS MODULES
# ==============================================================================
from kivy.uix.screenmanager  import ScreenManager, Screen, NoTransition
from kivy.uix.settings       import SettingsWithSidebar, SettingOptions

# ==============================================================================
# DEFINE 'WeatherFlowPiConsole' APP CLASS
# ==============================================================================
class wfpiconsole(App):

    # Define App class dictionary properties
    System  = DictProperty([('Time', '-'), ('Date', '-')])
    Sched   = DictProperty([])

    # Define App class configParser properties
    BarometerMax = ConfigParserProperty('-', 'System',  'BarometerMax', 'app')
    BarometerMin = ConfigParserProperty('-', 'System',  'BarometerMin', 'app')
    IndoorTemp   = ConfigParserProperty('-', 'Display', 'IndoorTemp',   'app')

    # Define display properties
    scaleFactor = NumericProperty(1)
    scaleSuffix = StringProperty('_lR.png')

    # BUILD 'WeatherFlowPiConsole' APP CLASS
    # --------------------------------------------------------------------------
    def build(self):

        # Calculate initial ScaleFactor and bind self.setScaleFactor to Window
        # on_resize
        self.window = Window
        self.setScaleFactor(self.window, self.window.width, self.window.height)
        self.window.bind(on_resize=self.setScaleFactor)

        # Initialise realtime clock
        self.Sched.realtimeClock = Clock.schedule_interval(partial(system.realtimeClock, self.System, self.config), 1.0)

        # Set Settings syle class
        self.settings_cls = SettingsWithSidebar

        # Initialise oscSERVER and oscCLIENT
        self.oscSERVER = OSCThreadServer()
        self.oscCLIENT = OSCClient('localhost', 3001)
        self.oscSERVER.listen(address=b'localhost', port=3002, default=True)
        self.oscSERVER.bind(b'/updateDisplay', self.updateDisplay)

        # Load Custom Panel KV file if present
        if Path('user/customPanels.py').is_file():
            Builder.load_file('user/customPanels.kv')

        # Initialise ScreenManager
        self.screenManager = screenManager(transition=NoTransition())
        self.screenManager.add_widget(CurrentConditions())
        return self.screenManager

    # SET DISPLAY SCALE FACTOR BASED ON SCREEN DIMENSIONS
    # --------------------------------------------------------------------------
    def setScaleFactor(self,instance,x,y):
        self.scaleFactor = max(min(x/800, y/480), 1)
        if self.scaleFactor > 1:
            self.scaleSuffix = '_hR.png'
        else:
            self.scaleSuffix = '_lR.png'

    # LOAD APP CONFIGURATION FILE
    # --------------------------------------------------------------------------
    def build_config(self, config):
        config.optionxform = str
        config.read('wfpiconsole.ini')

    # BUILD 'WeatherFlowPiConsole' APP CLASS SETTINGS
    # --------------------------------------------------------------------------
    def build_settings(self, settings):

        # Register setting types
        settings.register_type('ScrollOptions',     userSettings.ScrollOptions)
        settings.register_type('FixedOptions',      userSettings.FixedOptions)
        settings.register_type('ToggleTemperature', userSettings.ToggleTemperature)
        settings.register_type('ToggleHours',       userSettings.ToggleHours)
        settings.register_type('TextScale',         userSettings.TextScale)

        # Add required panels to setting screen. Remove Kivy settings panel
        settings.add_json_panel('Display',          self.config, data=userSettings.JSON('Display'))
        settings.add_json_panel('Primary Panels',   self.config, data=userSettings.JSON('Primary'))
        settings.add_json_panel('Secondary Panels', self.config, data=userSettings.JSON('Secondary'))
        settings.add_json_panel('Units',            self.config, data=userSettings.JSON('Units'))
        settings.add_json_panel('Feels Like',       self.config, data=userSettings.JSON('FeelsLike'))
        settings.add_json_panel('System',           self.config, data=userSettings.JSON('System'))
        self.use_kivy_settings = False
        self.settings = settings

    # OVERLOAD 'display_settings' TO OPEN SETTINGS SCREEN WITH SCREEN MANAGER
    # --------------------------------------------------------------------------
    def display_settings(self, settings):
        self.mainMenu.dismiss(animation=False)
        if not self.screenManager.has_screen('Settings'):
            self.settingsScreen = Screen(name='Settings')
            self.screenManager.add_widget(self.settingsScreen)
        self.settingsScreen.add_widget(self.settings)
        self.screenManager.current = 'Settings'
        return True

    # OVERLOAD 'close_settings' TO CLOSE SETTINGS SCREEN WITH SCREEN MANAGER
    # --------------------------------------------------------------------------
    def close_settings(self, *args):
        if self.screenManager.current == 'Settings':
            mainMenu().open(animation=False)
            self.screenManager.current = self.screenManager.previous()
            self.settingsScreen.remove_widget(self.settings)
            return True

    # OVERLOAD 'on_config_change' TO MAKE NECESSARY CHANGES TO CONFIG VALUES
    # WHEN REQUIRED
    # --------------------------------------------------------------------------
    def on_config_change(self, config, section, key, value):

        # Update current weather forecast when temperature or wind speed units
        # are changed
        if section == 'Units' and key in ['Temp', 'Wind']:
            self.Sched.metDownload = Clock.schedule_once(partial(forecast.startDownload, self, True))

        # Update current weather forecast, sunrise/sunset and moonrise/moonset
        # times when time format changed
        if section == 'Display' and key in 'TimeFormat':
            self.Sched.metDownload = Clock.schedule_once(partial(forecast.startDownload, self, True))
            astro.Format(self.CurrentConditions.Astro,   self.config, 'Sun')
            astro.Format(self.CurrentConditions.Astro,   self.config, 'Moon')

        # Update "Feels Like" temperature cutoffs in wfpiconsole.ini and the
        # settings screen when temperature units are changed
        if section == 'Units' and key == 'Temp':
            for Field in self.config['FeelsLike']:
                if 'c' in value:
                    Temp = str(round((float(self.config['FeelsLike'][Field]) - 32) * (5 / 9)))
                    self.config.set('FeelsLike', Field, Temp)
                elif 'f' in value:
                    Temp = str(round(float(self.config['FeelsLike'][Field]) * (9 / 5) + 32))
                    self.config.set('FeelsLike', Field, Temp)
            self.config.write()
            panels = self._app_settings.children[0].content.panels
            for Field in self.config['FeelsLike']:
                for panel in panels.values():
                    if panel.title == 'Feels Like':
                        for item in panel.children:
                            if isinstance(item, Factory.ToggleTemperature):
                                if item.title.replace(' ', '') == Field:
                                    item.value = self.config['FeelsLike'][Field]

        # Update barometer limits when pressure units are changed
        if section == 'Units' and key == 'Pressure':
            Units = ['mb', 'hpa', 'inhg', 'mmhg']
            Max   = ['1050', '1050', '31.0', '788']
            Min   = ['950', '950', '28.0', '713']
            self.config.set('System', 'BarometerMax', Max[Units.index(value)])
            self.config.set('System', 'BarometerMin', Min[Units.index(value)])

        # Update primary and secondary panels displayed on CurrentConditions
        # screen
        if section in ['PrimaryPanels', 'SecondaryPanels']:
            for Panel, Type in App.get_running_app().config['PrimaryPanels'].items():
                if Panel == key:
                    self.CurrentConditions.ids[Panel].clear_widgets()
                    self.CurrentConditions.ids[Panel].add_widget(eval(Type + 'Panel')())
                    break

        # Update button layout displayed on CurrentConditions screen
        if section == 'SecondaryPanels':
            ii = 0
            self.CurrentConditions.buttonList = []
            buttonList = ['Button' + Num for Num in ['One', 'Two', 'Three', 'Four', 'Five', 'Six']]
            for button in buttonList:
                self.CurrentConditions.ids[button].clear_widgets()
            for Panel, Type in App.get_running_app().config['SecondaryPanels'].items():
                if Type and Type != 'None':
                    self.CurrentConditions.ids[buttonList[ii]].add_widget(eval(Type + 'Button')())
                    self.CurrentConditions.buttonList.append([buttonList[ii], Panel, Type, 'Primary'])
                    ii += 1

            # Change 'None' for secondary panel selection to blank in config
            # file
            if value == 'None':
                self.config.set(section, key, '')
                self.config.write()
                panels = self._app_settings.children[0].content.panels
                for panel in panels.values():
                    if panel.title == 'Secondary Panels':
                        for item in panel.children:
                            if isinstance(item, Factory.SettingOptions):
                                if item.title.replace(' ', '') == key:
                                    item.value = ''
                                    break

        # Update Sager Forecast schedule
        if section == 'System' and key == 'SagerInterval':
            sagerForecast.Schedule(self.CurrentConditions.Sager, True, self)

        # Send configuration changed notification to Websocket service
        Retries = 0
        while Retries < 3:
            try:
                self.oscCLIENT.send_message(b'/websocket', [('reload_config').encode('utf8')])
                break
            except Exception:
                Retries += 1

    # START WEBSOCKET SERVICE
    # --------------------------------------------------------------------------
    def startWebsocketService(self, *largs):
        self.websocket = threading.Thread(target=websocketClient,
                                          daemon=True,
                                          name='Websocket')
        self.websocket.start()

    # STOP WEBSOCKET SERVICE
    # --------------------------------------------------------------------------
    def stopWebsocketService(self):
        self._websocket_is_running = False
        self.websocket.join()
        del self.websocket
        del self._websocket_is_running

    # UPDATE DISPLAY WITH NEW OBSERVATIONS SENT FROM WEBSOCKET SERVICE
    # --------------------------------------------------------------------------
    def updateDisplay(self, *payload):
        try:
            message = json.loads(payload[0].decode('utf8'))
            type    = payload[1].decode('utf8')
        except Exception:
            pass
        system.updateDisplay(type, message, self)


# ==============================================================================
# screenManager CLASS
# ==============================================================================
class screenManager(ScreenManager):
    pass

# ==============================================================================
# CurrentConditions CLASS
# ==============================================================================
class CurrentConditions(Screen):

    Sager = DictProperty([])
    Astro = DictProperty([])
    Obs   = DictProperty([])
    Met   = DictProperty([])

    def __init__(self, **kwargs):
        super(CurrentConditions, self).__init__(**kwargs)
        app = App.get_running_app()
        app.CurrentConditions = self
        app.Station  = status.Station(app)
        self.Sager   = properties.Sager()
        self.Astro   = properties.Astro()
        self.Met     = properties.Met()
        self.Obs     = properties.Obs()

        # Add display panels
        self.addPanels()

        # Start Websocket service
        app.startWebsocketService()

        # Schedule Station.getDeviceStatus to be called each second
        app.Sched.deviceStatus = Clock.schedule_interval(app.Station.get_deviceStatus, 1.0)

        # Initialise Sunrise, Sunset, Moonrise and Moonset times
        astro.SunriseSunset(self.Astro,   app.config)
        astro.MoonriseMoonset(self.Astro, app.config)

        # Schedule sunTransit and moonPhase functions to be called each second
        app.Sched.sunTransit = Clock.schedule_interval(partial(astro.sunTransit, self.Astro, app.config), 1)
        app.Sched.moonPhase  = Clock.schedule_interval(partial(astro.moonPhase,  self.Astro, app.config), 1)

        # Schedule WeatherFlow weather forecast download
        app.Sched.metDownload = Clock.schedule_once(partial(forecast.startDownload, app, False))

        # Generate Sager Weathercaster forecast
        threading.Thread(target=sagerForecast.Generate, args=(self.Sager, app), name="Sager", daemon=True).start()

    # ADD USER SELECTED PANELS TO CURRENT CONDITIONS SCREEN
    # --------------------------------------------------------------------------
    def addPanels(self):

        # Add primary panels to CurrentConditions screen
        for Panel, Type in App.get_running_app().config['PrimaryPanels'].items():
            self.ids[Panel].add_widget(eval(Type + 'Panel')())

        # Add secondary panel buttons to CurrentConditions screen
        self.buttonList = []
        ii = 0
        buttonList = ['Button' + Num for Num in ['One', 'Two', 'Three', 'Four', 'Five', 'Six']]
        for Panel, Type in App.get_running_app().config['SecondaryPanels'].items():
            if Type:
                self.ids[buttonList[ii]].add_widget(eval(Type + 'Button')())
                self.buttonList.append([buttonList[ii], Panel, Type, 'Primary'])
                ii += 1

    # SWITCH BETWEEN PRIMARY AND SECONDARY PANELS ON CURRENT CONDITIONS SCREEN
    # --------------------------------------------------------------------------
    def switchPanel(self, Instance, overideButton=None):

        # Determine ID of button that has been pressed
        for id, Object in App.get_running_app().CurrentConditions.ids.items():
            if Instance:
                if Object == Instance.parent.parent:
                    break
            else:
                if Object == overideButton:
                    break

        # Extract entry in buttonList that correponds to the button that has
        # been pressed
        for ii, button in enumerate(App.get_running_app().CurrentConditions.buttonList):
            if button[0] == id:
                break

        # Extract panel object the corresponds to the button that has been
        # pressed and determine new button type required
        Panel = App.get_running_app().CurrentConditions.ids[button[1]].children
        newButton = App.get_running_app().config[button[3] + 'Panels'][button[1]]

        # Destroy reference to old panel class attribute
        if hasattr(App.get_running_app(), newButton + 'Panel'):
            if len(getattr(App.get_running_app(), newButton + 'Panel')) > 1:
                try:
                    getattr(App.get_running_app(), newButton + 'Panel').remove(Panel[0])
                except ValueError:
                    print('Unable to remove panel reference from wfpiconsole class')
            else:
                delattr(App.get_running_app(), newButton + 'Panel')

        # Switch panel
        App.get_running_app().CurrentConditions.ids[button[1]].clear_widgets()
        App.get_running_app().CurrentConditions.ids[button[1]].add_widget(eval(button[2] + 'Panel')())
        App.get_running_app().CurrentConditions.ids[button[0]].clear_widgets()
        App.get_running_app().CurrentConditions.ids[button[0]].add_widget(eval(newButton + 'Button')())

        # Update button list
        if button[3] == 'Primary':
            App.get_running_app().CurrentConditions.buttonList[ii] = [button[0], button[1], newButton, 'Secondary']
        elif button[3] == 'Secondary':
            App.get_running_app().CurrentConditions.buttonList[ii] = [button[0], button[1], newButton, 'Primary']


# ==============================================================================
# RUN APP
# ==============================================================================
if __name__ == '__main__':
    try:
        wfpiconsole().run()
        if REBOOT:
            subprocess.call('sudo shutdown -r now', shell = True)
        elif SHUTDOWN:
            subprocess.call('sudo shutdown -h now', shell = True)
    except KeyboardInterrupt:
        wfpiconsole().stop()
