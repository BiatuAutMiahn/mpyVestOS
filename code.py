import supervisor
supervisor.status_bar.display = False
supervisor.status_bar.console = False

import time
import board
import pwmio
from analogio import AnalogIn
from digitalio import DigitalInOut, Direction, Pull
import usb_cdc
from adafruit_onewire.bus import OneWireBus
import adafruit_ds18x20
import asyncio
import displayio
import adafruit_displayio_ssd1306
from adafruit_bitmap_font import bitmap_font
from adafruit_display_text import label
import random
import rotaryio
# Main loop
# while True:

#     # update text property to change the text showing on the display
#     ts=time.monotonic_ns()

#     lbl_temp_set.text = "% 5s"%(str(random.randint(0,999)))
#     lbl_temp_amb.text = "tempAmb: % 5sF"%(str(round(random.random()*1000,1)))
#     lbl_temp_res.text = "tempRes: % 5sF"%(str(round(random.random()*1000,1)))
#     lbl_temp_ext.text = "tempExt: % 5sF"%(str(round(random.random()*1000,1)))
#     time.sleep(0.125)

class tempProbe(object):
    def __init__(self,ow,alias,serial_number):
        self.iAvg = 0
        self.tempAvg = 0.0
        self.tempAvgLast = 0
        self.tempNow = 0
        self.maxSamples = 10
        self.tempSamples = [0]*self.maxSamples
        self.timeLast = 0
        self.serial_number = None
        self.alias=alias
        scan = ow.scan()
        device=next((x for x in scan if x.serial_number in serial_number))
        self.dev = adafruit_ds18x20.DS18X20(ow, device)
        self.dev.resolution=9
        self.tReadDelay = None

    async def init(self):
        # start initial reading
        self.tReadDelay = self.dev.start_temperature_read()*1000

        #print("% 12s: Starting initial measurement..."%(self.alias))
        while self.tempAvg == 0:
            await self.tempMeasure(False)
            #print("% 12s: Awaiting measurement..."%(self.alias))
            await asyncio.sleep(0)


    async def tempMeasure(self,daemon=True):
        while True:
            tNow=time.monotonic()*1000
            if tNow-self.timeLast >= self.tReadDelay or self.timeLast==0:
                self.timeLast = tNow
                try:
                    self.tempNow = round(self.dev.read_temperature() * 1.8 + 32,1)
                    self.tempSamples[self.iAvg]=self.tempNow
                    self.iAvg+=1
                    if self.iAvg==self.maxSamples:
                        self.tempAvg=round(sum(self.tempSamples)/self.maxSamples,1)
                        if self.iAvg==self.maxSamples:
                            self.iAvg=0
                    if self.tempAvgLast != self.tempAvg:
                        print("% 12s: % 3.1f" % (self.alias,self.tempAvg))
                        self.tempAvgLast = self.tempAvg
                    self.tReadDelay = self.dev.start_temperature_read()*1000
                    if self.tReadDelay < 125:
                        self.tReadDelay = 125
                except:
                    pass
            if daemon:
                await asyncio.sleep(0.125)
            else:
                break

class Fan(object):
    def __init__(self, pinPWM, pinTach):
        self.pwm = pwmio.PWMOut(pinPWM, frequency=40000, duty_cycle=0)
        self.pwmMin = 16791 # Minimum required to cause an increase to FAN RPM.
        self.pwmMax = 65535 # The maximum PWM, no increase in RPM.
        self.pwmStep = (self.pwmMax-self.pwmMin)//98 # Minimum step required to cause a change in RPM.
        self.pwmLast = 0 # The last pwm value to avoid setting it repeatedly.

        #
        # exFan = pwmio.PWMOut(board.D9, frequency=20000, duty_cycle=0)
        # aExFanPwm = [16791, 0, 65535]
        # aExFanPwm[1] = (aExFanPwm[2]-aExFanPwm[0])//98
        # inFan = pwmio.PWMOut(board.SDA, frequency=20000, duty_cycle=0)
        # aInFanPwm = [16791, 0, 65535]
        # aInFanPwm[1] = (aInFanPwm[2]-aInFanPwm[0])//98
        # tExFan=0
        # iInFan = 0
        # pwmInFan = 0
        # iExFan = 0
        # pwmExFan = 0
        # iInFanLast = 0
        # iExFanLast = 0
        pass

        # # pwmHot = pwmio.PWMOut(board.D12, frequency=20000, duty_cycle=0)
        # # pwmCold = pwmio.PWMOut(board.D11, frequency=20000, duty_cycle=0)
        # # enHot = DigitalInOut(board.D13)
        # self.heatPump=Peltier(board.D13, board.D11, board.D12)

class Peltier(object):
    def __init__(self, pinEn, pinHot, pinCold):
        self.pwmMin = 13056 # 13056, Minimum required to cause an increase to current draw.
        self.pwmMax = 65535 # The maximum PWM, no increase in current draw.
        self.pwmStep = (self.pwmMax-self.pwmMin)//98 # Minimum step required to cause a change in current draw.
        self.pwmLast = 0 # The last pwm value to avoid setting it repeatedly.
        self.pwmHot = pwmio.PWMOut(pinHot, frequency=40000, duty_cycle=0)
        self.pwmCold = pwmio.PWMOut(pinCold, frequency=40000, duty_cycle=0)
        self.enable = DigitalInOut(pinEn)
        self.enable.direction = Direction.OUTPUT
        # aPeltierPwm[1] = (aPeltierPwm[2]-aPeltierPwm[0])//98
        pass

class tempController(object):
    def __init__(self):
        self.tNow=time.monotonic_ns()/1000000
        self.uiModeTimer=self.tNow
        self.perfTimerInit={x:0 for x in ['init','init.Serial','init.GPIO','init.OneWire','init.tempExt','init.tempAmb','init.tempRes','init.Peltier','init.Exaust','init.Display','init.Encoder','init.tempProbe']}
        #[0,[0]*10,0,0,0,0]
        self.perfTimer={x:[0,0,0,0,0,0] for x in ['doSerial','setTemp','setPump','setValve','setPeltier','setExaust','doDisplay','doEncoder']}
        self.reachedTarget = False
        self.sCon = None
        self.ow_bus = None
        self.tExaust = None
        self.tAmbient = None
        self.tReservoir = None
        self.heatPump = None
        self.fanExaust = None
        self.ioPump = None
        self.ioValve = None
        self.tempMode = 0
        self.pwmPeltier = 0
        self.tempTarget = 110
        self.tempExaust = 0
        self.tempReservoir = 65
        self.tempReservoirLast = 0
        self.tempExaust = 65
        self.tempExaustLast = 0
        self.tempTargetLast = 0
        self.tempMin = 40
        self.tempMax = 120
        self.powerSteps = [0.3125,0.625,1.25, 2.5, 5, 10]
        self.iExaustStep = 5
        self.iPeltierStep = 5
        self.iExaustPower = 0
        self.iPeltierPower = 0
        self.iExaustPowerLast = 0
        self.iPeltierPowerLast = 0
        self.iPeltier = 0
        self.iExaust = 0
        self.pwmExaust = 0
        self.bAuto = False
        self.bCalibrate = False
        self.bPump = False
        self.bValve = False
        self.tMode = 0
        self.timeStampPeltier = 0
        self.timeStampExaust = 0
        self.bDev = False
        self.timerDisplay = 0
        self.lastDisplay=[0]*10
        self.encoder=None
        self.encLast = None
        self.encPos = None
        self.ioEnc = None
        self.encSw = None
        self.blinkTimer = None
        self.tempSetTimeout = 0
        self.uiMode = 0
        self.uiTempSet = 0
        self.blinkState = False
        self.encSwLast = None
        self.statPerf=1
        self.statPerfTimer=None
        #self.perfTimer[0][0]=time.monotonic_ns()-self.perfTimer[0]
    async def init(self):
        self.perfTimerInit['init']=time.monotonic_ns()
        # 13 = iPeltier EN
        # 12 = iPeltier R_PWM
        # 11 = iPeltier L_PWM
        # 10 = ExFan Tach
        # 9 = ExFan PWM
        # 5 = Circulation Valve
        # RX = Circulation Pump
        # D12, YLW, RPWM
        # D11, ORG, LPWM
        # D10, GRN, R_EN
        # D9,  BLU, L_EN
        print("Initializing System: ",end='')
        print("Serial",end='')
        self.perfTimerInit['init.Serial']=time.monotonic_ns()
        self.sCon = usb_cdc.console
        self.perfTimerInit['init.Serial']=time.monotonic_ns()-self.perfTimerInit['init.Serial']
        print(", GPIO",end='')
        self.perfTimerInit['init.GPIO']=time.monotonic_ns()
        self.ioPump = DigitalInOut(board.RX)
        self.ioValve = DigitalInOut(board.D5)
        self.ioPump.direction = Direction.OUTPUT
        self.ioValve.direction = Direction.OUTPUT
        self.perfTimerInit['init.GPIO']=time.monotonic_ns()-self.perfTimerInit['init.GPIO']
        print(", OneWire",end='')
        self.perfTimerInit['init.OneWire']=time.monotonic_ns()
        self.ow_bus = OneWireBus(board.TX)
        self.perfTimerInit['init.OneWire']=time.monotonic_ns()-self.perfTimerInit['init.OneWire']
        print(", DS18B20",end='')
        self.perfTimerInit['init.tempExt']=time.monotonic_ns()
        self.tExaust = tempProbe(self.ow_bus,"tempExaust",bytearray(b'\x03\xb3\x81\xe3U<'))
        self.perfTimerInit['init.tempExt']=time.monotonic_ns()-self.perfTimerInit['init.tempExt']
        self.perfTimerInit['init.tempAmb']=time.monotonic_ns()
        self.tAmbient = tempProbe(self.ow_bus,"tempAmbient",bytearray(b'.\x7fW\x04]<'))
        self.perfTimerInit['init.tempAmb']=time.monotonic_ns()-self.perfTimerInit['init.tempAmb']
        self.perfTimerInit['init.tempRes']=time.monotonic_ns()
        self.tReservoir = tempProbe(self.ow_bus,"tempReservoir",[bytearray(b'$F\x81$@<'),bytearray(b',F\x81\xe3@<')])
        self.perfTimerInit['init.tempRes']=time.monotonic_ns()-self.perfTimerInit['init.tempRes']
        print(", Peltier",end='')
        self.perfTimerInit['init.Peltier']=time.monotonic_ns()
        self.heatPump=Peltier(board.D13, board.D11, board.D12)
        self.perfTimerInit['init.Peltier']=time.monotonic_ns()-self.perfTimerInit['init.Peltier']
        print(", Fan(s)",end='')
        self.perfTimerInit['init.Exaust']=time.monotonic_ns()
        self.fanExaust=Fan(board.D9,board.D10)
        self.perfTimerInit['init.Exaust']=time.monotonic_ns()-self.perfTimerInit['init.Exaust']
        print(", Display",end='')
        self.perfTimerInit['init.Display']=time.monotonic_ns()
        displayio.release_displays()
        self.i2c = board.I2C()
        self.display = adafruit_displayio_ssd1306.SSD1306(displayio.I2CDisplay(self.i2c, device_address=0x3d), width=128, height=64)
        self.display.rotation=270
        self.display
        self.display.root_group[0].hidden = False
        self.display.root_group[1].hidden = True # logo
        self.display.root_group[2].hidden = True # status bar
        supervisor.reset_terminal(self.display.width, self.display.height * 2)
        self.display.root_group[0].y = 0
        self.font_exlg = bitmap_font.load_font("/Consolas-Temp-36.bdf")
        self.font_lg_lg = bitmap_font.load_font("/Consolas-Temp-24.bdf")
        self.font_lg_sh = bitmap_font.load_font("/Consolas-Temp-28.bdf")
        self.font_sm = bitmap_font.load_font("/Consolas-8.bdf")
        self.main_group = displayio.Group()
        self.display.show(self.main_group)
        self.lbl_temp_set = label.Label(font=self.font_lg_lg)
        self.lbl_temp_set.anchor_point = (0,0)
        if len(str(self.tReservoir.tempAvg))>4:
            self.lbl_temp_set.font=self.font_lg_lg
            self.lbl_temp_set.anchored_position = (0, 8)
        else:
            self.lbl_temp_set.font=self.font_lg_sh
            self.lbl_temp_set.anchored_position = (1, 8)
        self.lbl_temp_set.text="%s"%(str(self.tReservoir.tempAvg))

        yoff=40
        self.lbl_temp_trg      = self.genLbl("tempTrg: % 5sF"%(str(self.tempTarget)),2,yoff)
        self.lbl_temp_amb      = self.genLbl("tempAmb: % 5sF"%(str(self.tAmbient.tempAvg)),2,yoff+10)
        self.lbl_temp_res      = self.genLbl("tempRes: % 5sF"%(str(self.tReservoir.tempAvg)),2,yoff+20)
        self.lbl_temp_ext      = self.genLbl("tempExt: % 5sF"%(str(self.tExaust.tempAvg)),2,yoff+30)
        self.lbl_state_peltier = self.genLbl("   iPlt: % 3s%%"%(str(self.iPeltierPower)),2,yoff+40)
        self.lbl_state_exfan   = self.genLbl("iExaust: % 3d%%"%(self.iExaustPower),2,yoff+50)
        self.lbl_state_pump    = self.genLbl(" bPump: % 5s"%("True" if self.bPump else "False"),2,yoff+60)
        self.lbl_state_valve   = self.genLbl("bValve: % 5s"%("True" if self.bValve else "False"),2,yoff+70)
        self.lbl_state_auto   = self.genLbl("bAuto: % 5s"%("True" if self.bAuto else "False"),2,yoff+80)

        self.main_group.append(self.lbl_temp_trg)
        self.main_group.append(self.lbl_temp_amb)
        self.main_group.append(self.lbl_temp_res)
        self.main_group.append(self.lbl_temp_ext)
        self.main_group.append(self.lbl_state_pump)
        self.main_group.append(self.lbl_state_valve)
        self.main_group.append(self.lbl_state_peltier)
        self.main_group.append(self.lbl_state_exfan)
        self.main_group.append(self.lbl_temp_set)
        self.main_group.append(self.lbl_state_auto)
        self.perfTimerInit['init.Display']=time.monotonic_ns()-self.perfTimerInit['init.Display']
        print(", Encoder",end='')
        self.perfTimerInit['init.Encoder']=time.monotonic_ns()
        self.encoder = rotaryio.IncrementalEncoder(board.A4, board.A5)
        self.ioEnc = DigitalInOut(board.D7)
        self.ioEnc.direction = Direction.INPUT
        self.ioEnc.pull = Pull.UP
        self.uiTempSet = self.tempTarget
        self.encSwLast = self.ioEnc.value
        self.encSw = self.ioEnc.value
        self.perfTimerInit['init.Encoder']=time.monotonic_ns()-self.perfTimerInit['init.Encoder']
        print("...Done")

        # Initialize DS18B20 Temperature Probes
        print("Initializing Temp Probes...")
        self.perfTimerInit['init.tempProbe']=time.monotonic_ns()
        tasks=[]
        tasks.append(asyncio.create_task(self.tExaust.init()))
        tasks.append(asyncio.create_task(self.tAmbient.init()))
        tasks.append(asyncio.create_task(self.tReservoir.init()))
        # tasks.append(asyncio.create_task(doTest(tTest)))
        await asyncio.gather(*tasks)
        self.perfTimerInit['init.tempProbe']=time.monotonic_ns()-self.perfTimerInit['init.tempProbe']
        print("Initializing Temp Probes...done")
        if self.bAuto:
            print("bAuto: 1")
        self.perfTimerInit['init']=time.monotonic_ns()-self.perfTimerInit['init']
        if self.statPerf:
            print('[PerfInit]')
            for k,v in self.perfTimerInit.items():
                print("% 15s: % 5.4f"%(k,v/1000000))
            self.statPerf=0
        print('')
        print("System Ready.")
    def genLbl(self,text,x,y):
        lbl = label.Label(font=self.font_sm, text=text)
        lbl.anchor_point = (0, 0)
        lbl.anchored_position = (x, y)    
        return lbl
    # Serial UI
    async def doSerial(self):
        while True:
            self.perfTimer['doSerial'][0]=time.monotonic_ns()
            sBuf=""
            iAvail = self.sCon.in_waiting
            while iAvail:
                sBuf += self.sCon.read(iAvail).decode("utf-8")
                iAvail = self.sCon.in_waiting
            if sBuf == "Q": # Reboot
                supervisor.reload()
            elif sBuf == "A": # Toggle Automatic Mode
                self.bAuto=False if self.bAuto else True
                print("% 13s: %s"%("bAuto",self.bAuto))
            elif sBuf == "S": # Print Per Stats
                if self.statPerf==0:
                    self.statPerf=2
                    self.statPerfTimer=0
                    print("% 13s: %s"%("statPerf",self.statPerf))
                elif self.statPerf==2:
                    self.statPerf=0
                    print("% 13s: %s"%("statPerf",self.statPerf))
            elif sBuf == "s": # Print Per Stats
                if self.statPerf==0:
                    self.statPerf=1
                    print("% 13s: %s"%("statPerf",self.statPerf))
            elif sBuf == "{": # Decrease Target Temp
                if self.tempTarget > self.tempMin:
                    self.tempTarget -= 1
                    print("% 13s: %s"%("tempTarget",self.tempTarget))
            elif sBuf == "}": # Increase Target Temp
                if self.tempTarget < self.tempMax:
                    self.tempTarget += 1
                    print("% 13s: %s"%("tempTarget",self.tempTarget))
            elif sBuf == "P": # Reset Target Temp for mode.
                if self.tMode: # Heat
                    self.tempTarget=110
                else:
                    self.tempTarget=65
                print("% 13s: %s"%("tempTarget",self.tempTarget))
            elif sBuf == "O": # Switch Hot/Cold Mode
                self.tMode = False if self.tMode else True
                self.iPeltierPower=0
                self.iPeltierStep=5
                if self.tMode: # Heat
                    self.tempTarget=65
                else:
                    self.tempTarget=110
                print("% 13s: %s"%("tMode",self.tMode))
                print("% 13s: %s"%("iPeltierPower",self.iPeltierPower))
                print("% 13s: %s"%("tempTarget",self.tempTarget))
            # if self.bDev:
            elif sBuf == "Z": # Decrease Target Temp
                if self.iPeltierStep > 0:
                    self.iPeltierStep -= 1
                    print("% 13s: %s"%("iPeltierStep",self.iPeltierStep))
            elif sBuf == "X": # Increase Target Temp
                if self.iPeltierStep < 5:
                    self.iPeltierStep += 1
                    print("% 13s: %s"%("iPeltierStep",self.iPeltierStep))
            if not self.bAuto:
                # elif sBuf=="[":
                #     if iInFan>0:
                #         iInFan-=5
                # elif sBuf == "]":
                #     if iInFan<100:
                #         iInFan+=5
                if sBuf == ";":
                    if self.iExaustPower > 0:
                        self.iExaustPower -= 5
                        print("% 13s: %s"%("iExaustPower",self.iExaustPower))
                elif sBuf == "'":
                    if self.iExaustPower < 100:
                        self.iExaustPower += 5
                        print("% 13s: %s"%("iExaustPower",self.iExaustPower))
                elif sBuf == "L": # Reset Fan (only when Peltier power is 0)
                    if self.iPeltierPower==0:
                        self.iExaustPower=0
                        print("% 13s: %s"%("iExaustPower",self.iExaustPower))
                elif sBuf == "K":
                    if self.iExaustStep < 3:
                        self.iExaustStep += 1
                        print("% 13s: %s"%("iExaustStep",self.iExaustStep))
                    else:
                        self.iExaustStep = 0
                        print("% 13s: %s"%("iExaustStep",self.iExaustStep))
                elif sBuf == ",":
                    # if self.bCalibrate:
                    #     self.iPeltierPower -= 128
                    #     print("% 13s: %s"%("iPeltierPower",self.iPeltierPower))
                    if self.iPeltierPower > -100:
                        self.iPeltierPower -= self.powerSteps[self.iPeltierStep]
                        print("% 13s: %s"%("iPeltierPower",self.iPeltierPower))
                elif sBuf == ".":
                    # if self.bCalibrate:
                    #     self.iPeltierPower += 128
                    #     print("% 13s: %s"%("iPeltierPower",self.iPeltierPower))
                    if self.iPeltierPower < 100:
                        self.iPeltierPower += self.powerSteps[self.iPeltierStep]
                        print("% 13s: %s"%("iPeltierPower",self.iPeltierPower))
                elif sBuf == "m": # Reset Peilter Power Level
                    self.iPeltierPower = 0
                    print("% 13s: %s"%("iPeltierPower",self.iPeltierPower))
                elif sBuf == "/": # Toggle Pump
                    self.bPump = False if self.bPump else True
                    print("% 13s: %s"%("bPump",self.bPump))
                elif sBuf == "?": # Toggle Valve
                    self.bValve = False if self.bValve else True
                    print("% 13s: %s"%("bValve",self.bValve))
                #await asyncio.sleep(0.125)
            self.perfTimer['doSerial'][0]=time.monotonic_ns()-self.perfTimer['doSerial'][0]
            await asyncio.sleep(0.01)
    def calcPower(self, tempLast, tempNow, tempTarget, iPower, iPrecision, iMode = 0):
        if iMode:
            iPower=-iPower
            if tempLast <= tempTarget:
                if tempNow < tempTarget:
                    if iPower > 0:
                        iPower -= self.powerSteps[iPrecision]
                else:
                    if iPrecision > 0 and tempNow > tempTarget:
                        iPrecision -= 1
                    if iPower < 100:
                        iPower += self.powerSteps[iPrecision]
            else:
                if tempNow > tempTarget:
                    if iPower < 100:
                        iPower += self.powerSteps[iPrecision]
                if tempNow < tempTarget:
                    if iPower>0:
                        iPower -= self.powerSteps[iPrecision]
            return -iPower, iPrecision    
        else:
            if tempLast >= tempTarget:
                if tempNow > tempTarget:
                    if iPower > 0:
                        iPower -= self.powerSteps[iPrecision]
                else:
                    if iPrecision > 0 and tempNow < tempTarget:
                        iPrecision -= 1
                    if iPower < 100:
                        iPower += self.powerSteps[iPrecision]
            else:
                if tempNow < tempTarget:
                    if iPower < 100:
                        iPower += self.powerSteps[iPrecision]
                if tempNow > tempTarget:
                    if iPower>0:
                        iPower -= self.powerSteps[iPrecision]
            return iPower, iPrecision
    async def setTemp(self):
        while True:
            self.perfTimer['setTemp'][0]=time.monotonic_ns()
            if not self.bAuto:
                self.perfTimer['setTemp'][0]=time.monotonic_ns()-self.perfTimer['setTemp'][0]
                await asyncio.sleep(0.125)
                continue
            self.tempReservoir=self.tReservoir.tempAvg
            tempTargetDiff=abs(round(self.tempTarget)-round(self.tempReservoir))
            self.tempMode=round(self.tempTarget)<round(self.tAmbient.tempAvg) # 0:Heating, 1:Cooling
            # if self.tempMode:
            #     if self.iPeltierStep==5:
            #         timeDelay=20000
            #     elif self.iPeltierStep==4:
            #         timeDelay=40000
            #     elif self.iPeltierStep==3:
            #         timeDelay=60000
            #     elif self.iPeltierStep==2:
            #         timeDelay=80000
            #     elif self.iPeltierStep==1:
            #         timeDelay=100000
            #     elif self.iPeltierStep==0:
            #         timeDelay=120000
            # else:
            timeDelay=250
            if self.iPeltierStep==5:
                timeDelay=10000
            elif self.iPeltierStep==4:
                timeDelay=20000
            elif self.iPeltierStep==3:
                timeDelay=30000
            elif self.iPeltierStep==2:
                timeDelay=40000
            elif self.iPeltierStep==1:
                timeDelay=50000
            elif self.iPeltierStep==0:
                timeDelay=60000

            if (self.tempMode and self.tempReservoir<(self.tempTarget-2)) or (not self.tempMode and self.tempReservoir>(self.tempTarget-5)):
                if not self.reachedTarget:
                    self.reachedTarget=True
                    if (not self.tempMode and self.tempReservoir>(self.tempTarget-5)):                    
                        self.iPeltierPower=0
                    self.iPeltierStep=1
                    timeDelay=250
            else:
                if not self.reachedTarget:
                    if tempTargetDiff>=2:
                        timeDelay=250
                # else:
                #     if tempTargetDiff>=10:
                #         timeDelay=1000
                #     elif tempTargetDiff>=5:
                #         timeDelay=5000
                #     if tempTargetDiff>=2:
                #         timeDelay=10000
                #     # if tempTargetDiff>=1:
                #     #     timeDelay=30000
            if self.tNow-self.timeStampPeltier>=timeDelay:#self.tempReservoirLast!=round(self.tempReservoir) or ((not self.reachedTarget or (not self.tempMode and self.tempReservoir>self.tempTarget) or (self.tempMode and self.tempReservoir<self.tempTarget)) and timeNow-self.timeStampPeltier>=timeDelay):# or (not self.tempMode and tempTargetDiff>=4 and self.tempReservoir>self.tempTarget):
                # print(self.reachedTarget,self.tNow,self.timeStampPeltier,self.tNow-self.timeStampPeltier,timeDelay)
                # print(self.tNow-self.timeStampPeltier>=timeDelay)
                # print((not self.tempMode and self.tempReservoir>self.tempTarget))
                # print((self.tempMode and self.tempReservoir<self.tempTarget))
                # print(((not self.reachedTarget or (not self.tempMode and self.tempReservoir>self.tempTarget) or (self.tempMode and self.tempReservoir<self.tempTarget)) and self.tNow-self.timeStampPeltier>=timeDelay))
                self.timeStampPeltier = self.tNow
                self.iPeltierPower, self.iPeltierStep=self.calcPower(round(self.tempReservoirLast),round(self.tempReservoir),self.tempTarget,self.iPeltierPower,self.iPeltierStep,self.tempMode)
                print(self.tempReservoirLast,self.tempReservoir,self.tempTarget,self.iPeltierPower,self.iPeltierStep,self.tempMode)
                if self.iPeltierPower!=self.iPeltierPowerLast:
                    self.iPeltierPowerLast=self.iPeltierPower
                    print("% 13s: %s"%("iPeltierPower",self.iPeltierPower))
                if round(self.tempReservoir)!=self.tempReservoirLast:
                    self.tempReservoirLast=round(self.tempReservoir)
            if (not self.tempMode and self.tempReservoir>=(self.tempTarget+5)) and self.iPeltierPower!=0:
                self.iPeltierPower=0
            self.perfTimer['setTemp'][0]=time.monotonic_ns()-self.perfTimer['setTemp'][0]
            await asyncio.sleep(0.125)
    async def setPump(self):
        while True:
            self.perfTimer['setPump'][0]=time.monotonic_ns()
            if self.bAuto:
                if abs(self.tReservoir.tempAvg - self.tAmbient.tempAvg) >= 1 or self.iPeltierPower!=0:
                    if not self.bPump:
                        self.bPump = True
                        print("% 13s: %s"%("bPump",self.bPump))
                else:
                    if self.bPump:
                        self.bPump = False
                        print("% 13s: %s"%("bPump",self.bPump))
            if self.ioPump.value!=self.bPump:
                self.ioPump.value=self.bPump
            self.perfTimer['setPump'][0]=time.monotonic_ns()-self.perfTimer['setPump'][0]
            await asyncio.sleep(0.125)
    async def setValve(self):
        while True:
            self.perfTimer['setValve'][0]=time.monotonic_ns()
            if self.bAuto:
                if (not self.tempMode and (abs(self.tReservoir.tempAvg - self.tempTarget) <= 2 or self.tReservoir.tempAvg>=self.tempTarget)) or (self.tempMode and self.tReservoir.tempAvg<=self.tempTarget):
                    if self.bValve:
                        self.bValve = False
                        print("% 13s: %s"%("bValve",self.bValve))
                elif abs(self.tReservoir.tempAvg - self.tempTarget) > 4:
                    if not self.bValve:
                        self.bValve = True
                        print("% 13s: %s"%("bValve",self.bValve))
            if self.ioValve.value!=self.bValve:
                self.ioValve.value=self.bValve
            self.perfTimer['setValve'][0]=time.monotonic_ns()-self.perfTimer['setValve'][0]
            await asyncio.sleep(0.125)
    async def setPeltier(self):
        while True:
            self.perfTimer['setPeltier'][0]=time.monotonic_ns()
            if self.iPeltierPower!=0:
                if self.iPeltierPower>100:
                    self.iPeltierPower=100
                if self.iPeltierPower<-100:
                    self.iPeltierPower=-100
                if self.tReservoir.tempAvg<=35 or self.tExaust.tempAvg>=140:
                    self.iPeltierPower=0
                self.pwmPeltier=self.heatPump.pwmMin+int((self.heatPump.pwmStep*(abs(self.iPeltierPower)-1)))
                if self.heatPump.pwmHot!=self.pwmPeltier:
                    if self.heatPump.enable.value!=True:
                        self.heatPump.enable.value=True
                if self.pwmPeltier>self.heatPump.pwmMax:
                    self.pwmPeltier=self.heatPump.pwmMax
                if self.pwmPeltier<=self.heatPump.pwmMin:
                    self.pwmPeltier=0
            if self.iPeltierPower>0: # Heat Mode
                    if self.heatPump.pwmCold.duty_cycle!=0:
                        self.heatPump.pwmCold.duty_cycle = 0
                    self.heatPump.pwmHot.duty_cycle=self.pwmPeltier
            elif self.iPeltierPower<0: # Cool Mode
                    if self.heatPump.pwmHot.duty_cycle!=0:
                        self.heatPump.pwmHot.duty_cycle = 0
                    self.heatPump.pwmCold.duty_cycle=self.pwmPeltier
            else:
                if self.heatPump.enable.value!=False:
                    self.heatPump.enable.value=False
                if self.heatPump.pwmHot.duty_cycle!=0:
                    self.heatPump.pwmHot.duty_cycle = 0
                if self.heatPump.pwmCold.duty_cycle!=0:
                    self.heatPump.pwmCold.duty_cycle = 0
            self.perfTimer['setPeltier'][0]=time.monotonic_ns()-self.perfTimer['setPeltier'][0]
            await asyncio.sleep(0.125)
    async def setExaust(self):
        while True:
            self.perfTimer['setExaust'][0]=time.monotonic_ns()
            if self.bAuto:
                if round(self.tempTarget)>round(self.tAmbient.tempAvg):
                    # if cooling, set to low-medium speed
                    if self.iExaustPower!=20:
                        self.iExaustPower=20
                    if self.iExaustPower!=self.iExaustPowerLast:
                        self.iExaustPowerLast=self.iExaustPower
                        print("% 13s: %s"%("iExaustPower",self.iExaustPower))
                else:
                    if self.iExaustPower!=100:
                        self.iExaustPower=100
                    # self.tempExaust=self.tExaust.tempAvg
                    # tempTargetDiff=round(self.tReservoir.tempAvg)-round(self.tempExaust)
                    # timeDelay=0
                    # if tempTargetDiff>=10:
                    #     timeDelay=500
                    # elif tempTargetDiff>=5:
                    #     timeDelay=10000
                    # elif tempTargetDiff>=2:
                    #     timeDelay=20000
                    # else:
                    #     timeDelay=30000
                    # timeNow=time.monotonic()*1000
                    # if timeNow-self.timeStampExaust>timeDelay or self.tempExaustLast!=self.tempExaust:
                    #     self.iExaustPower, self.iExaustStep=self.calcPower(self.tempExaustLast,self.tempExaust,self.tReservoir.tempAvg,-self.iExaustPower,self.iExaustStep,1)
                    #     self.iExaustPower=-self.iExaustPower
                    #     self.tempExaustLast=self.tempExaust
                    #     self.timeStampExaust=timeNow
                    if self.iExaustPower!=self.iExaustPowerLast:
                        self.iExaustPowerLast=self.iExaustPower
                        print("% 13s: %s"%("iExaustPower",self.iExaustPower))
            if self.tempExaust>=100:
                self.iExaustPower=100
                if self.iExaustPower!=self.iExaustPowerLast:
                    self.iExaustPowerLast=self.iExaustPower
                    print("% 13s: %s"%("tempExaust",self.tempExaust))
                    print("% 13s: %s"%("iExaustPower",self.iExaustPower))
            self.pwmExaust=self.fanExaust.pwmMin+int((self.fanExaust.pwmStep*(abs(self.iExaustPower)-1)))
            if self.pwmExaust>self.fanExaust.pwmMax:
                self.pwmExaust=self.fanExaust.pwmMax
            if self.pwmExaust<=self.fanExaust.pwmMin:
                self.pwmExaust=0
            if self.fanExaust.pwm.duty_cycle!=self.pwmExaust:
                self.fanExaust.pwm.duty_cycle=self.pwmExaust
            self.perfTimer['setExaust'][0]=time.monotonic_ns()-self.perfTimer['setExaust'][0]
            await asyncio.sleep(0.125)
    async def doDisplay(self):
        while True:
            self.perfTimer['doDisplay'][0]=time.monotonic_ns()
            if self.uiMode==2:                
                if self.tNow-self.blinkTimer>=500 or self.blinkState==0:
                    self.blinkTimer=self.tNow
                    if self.blinkState==0 or self.blinkState==2:
                        self.lbl_temp_set.font=self.font_exlg
                        self.lbl_temp_set.text = "%s"%(str(self.uiTempSet))
                        if len(str(self.uiTempSet))>2:
                            self.lbl_temp_set.anchored_position = (2, 4)
                        else:
                            self.lbl_temp_set.anchored_position = (10, 4)
                        self.blinkState=1
                        if self.tNow-self.uiModeTimer>=10000:
                            self.uiTempSet = self.tempTarget
                            if self.bAuto:
                                self.uiMode = 1
                            else:
                                self.uiMode = 0
                            if len(str(self.tReservoir.tempAvg))>4:
                                self.lbl_temp_set.font=self.font_lg_lg
                                self.lbl_temp_set.anchored_position = (0, 8)
                            else:
                                self.lbl_temp_set.font=self.font_lg_sh
                                self.lbl_temp_set.anchored_position = (1, 8)
                            self.lbl_temp_set.text = "%s"%(str(self.tReservoir.tempAvg))
                    else:
                            self.lbl_temp_set.text = ''
                            self.blinkState = 2
            else:
                if self.lastDisplay[0]!=self.tReservoir.tempAvg:
                    self.lastDisplay[0]=self.tReservoir.tempAvg
                    if len(str(self.tReservoir.tempAvg))>4:
                        self.lbl_temp_set.font=self.font_lg_lg
                        self.lbl_temp_set.anchored_position = (0, 8)
                    else:
                        self.lbl_temp_set.font=self.font_lg_sh
                        self.lbl_temp_set.anchored_position = (1, 8)
                    self.lbl_temp_set.text = "%s"%(str(self.tReservoir.tempAvg))
            if self.lastDisplay[1]!=self.tAmbient.tempAvg:
                self.lastDisplay[1]=self.tAmbient.tempAvg
                self.lbl_temp_amb.text      = "tempAmb: % 5sF"%(str(self.tAmbient.tempAvg))
            if self.lastDisplay[2]!=self.tReservoir.tempAvg:
                self.lastDisplay[2]=self.tReservoir.tempAvg
                self.lbl_temp_res.text      = "tempRes: % 5sF"%(str(self.tReservoir.tempAvg))
            if self.lastDisplay[3]!=self.tExaust.tempAvg:
                self.lastDisplay[3]=self.tExaust.tempAvg
                self.lbl_temp_ext.text      = "tempExt: % 5sF"%(str(self.tExaust.tempAvg))
            if self.lastDisplay[4]!=self.iPeltierPower:
                self.lastDisplay[4]=self.iPeltierPower
                self.lbl_state_peltier.text = "   iPlt: % 3s%%"%(str(self.iPeltierPower))
            if self.lastDisplay[5]!=self.iExaustPower:
                self.lastDisplay[5]=self.iExaustPower
                self.lbl_state_exfan.text   = "iExaust: % 3d%%"%(self.iExaustPower)
            if self.lastDisplay[6]!=self.bPump:
                self.lastDisplay[6]=self.bPump
                self.lbl_state_pump.text    = " bPump: % 5s"%("True" if self.bPump else "False")
            if self.lastDisplay[7]!=self.bValve:
                self.lastDisplay[7]=self.bValve
                self.lbl_state_valve.text   = "bValve: % 5s"%("True" if self.bValve else "False")
            if self.lastDisplay[8]!=self.bAuto:
                self.lastDisplay[8]=self.bAuto
                self.lbl_state_auto.text   = "bAuto: % 5s"%("True" if self.bAuto else "False")
            if self.lastDisplay[9]!=self.tempTarget:
                self.lastDisplay[9]=self.tempTarget
                self.lbl_temp_trg.text      = "tempTrg: % 5sF"%(str(self.tempTarget))
            self.perfTimer['doDisplay'][0]=time.monotonic_ns()-self.perfTimer['doDisplay'][0]
            await asyncio.sleep(0.125)
    async def doEncoder(self):
        while True:
            self.perfTimer['doEncoder'][0]=time.monotonic_ns()
            if self.encSw!=self.ioEnc.value:
                self.encSw=self.ioEnc.value
                print("% 12s:%s"%('encSw',self.encSw))
                if self.encSw!=self.encSwLast:
                    self.encSwLast=self.encSw
                    if self.encSw:
                        if self.uiMode==0:
                            if not self.bAuto:
                                self.bAuto=True
                                self.uiMode=1
                        elif self.uiMode==1:
                            if self.bAuto:
                                self.iPeltierPower=0
                                self.iExaustPower=0
                                self.iPeltierStep=5
                                self.iExaustStep=5
                                self.bValve = True
                                self.bPump = False
                                self.bAuto=False
                                self.uiMode=0
                        elif self.uiMode==2:
                            self.tempTarget = self.uiTempSet
                            if not self.bAuto:
                                self.bAuto=True
                                self.uiMode=1
                            else:
                                self.iPeltierPower=0
                                self.iExaustPower=0
                                self.iPeltierStep=5
                                self.iExaustStep=5
                                self.uiMode=1

                        # elif self.uiMode==3:
                        #     pass
                        # elif self.uiMode==4:
                        #     pass
            self.encPos = self.encoder.position
            if self.encLast is None or self.encPos != self.encLast:
                #print(self.encPos)
                if not self.encPos==0:
                    if self.encPos<-1:
                        self.encPos=-1
                    elif self.encPos>1:
                        self.encPos=1
                    print("% 12s:%s"%('encPos',self.encPos))
                    if self.uiMode!=2:
                        self.uiTempSet = self.tempTarget
                        if (self.encPos>0 and self.uiTempSet<self.tempMax) or (self.encPos<0 and self.uiTempSet>self.tempMin):
                            self.uiTempSet += self.encPos
                        self.blinkTimer = self.tNow
                        self.uiModeTimer = self.tNow
                        self.uiMode=2
                        self.blinkState=0
                    elif self.uiMode==2:
                        if (self.encPos>0 and self.uiTempSet<self.tempMax) or (self.encPos<0 and self.uiTempSet>self.tempMin):
                            self.uiTempSet += self.encPos
                            self.blinkState = 0
                            self.uiModeTimer = self.tNow
                            self.blinkTimer = self.tNow
                self.encoder.position = 0
                self.encPos = 0
                self.encLast = 0
            self.encLast = self.encPos
            self.perfTimer['doEncoder'][0]=time.monotonic_ns()-self.perfTimer['doEncoder'][0]
            await asyncio.sleep(0)
    # async def doTemps(self):
    #     await self.tExaust.tempMeasure()
    #     await self.tReservoir.tempMeasure()
    #     await self.tAmbient.tempMeasure()
    # async def doEvents2(self):
    #     self.perfTimer[21]=time.monotonic_ns()
    #     await self.doSerial()
    #     await self.setExaust()
    #     await self.setPump()
    #     await self.setValve()
    #     await self.setTemp()
    #     await self.setPeltier()
    #     await self.doEncoder()
    #     self.perfTimer[21]=time.monotonic_ns()-self.perfTimer[21]
    
    async def doTime(self):
        while True:
            self.tNow=time.monotonic_ns()/1000000
            await asyncio.sleep(0)
    async def doPerfStat(self):
        while True:
            #[0,[0]*10,0,0,0,0]
            for k in self.perfTimer.keys():
                # Update Rolling Avg
                if self.perfTimer[k][2]>1000:
                    self.perfTimer[k][2]=0
                    self.perfTimer[k][1]=self.perfTimer[k][0]
                self.perfTimer[k][1]+=self.perfTimer[k][0]
                self.perfTimer[k][2]+=1

                # Sum Avg
                self.perfTimer[k][3]=self.perfTimer[k][1]/self.perfTimer[k][2]

                # Handle Min
                if (self.perfTimer[k][0]<self.perfTimer[k][4] and self.perfTimer[k][0]>0) or self.perfTimer[k][4]==0:
                    self.perfTimer[k][4]=self.perfTimer[k][0]
                # Handle Max
                if self.perfTimer[k][0]>self.perfTimer[k][5]:
                    self.perfTimer[k][5]=self.perfTimer[k][0]
            if self.statPerf==1 or (self.statPerf==2 and self.tNow-self.statPerfTimer>=1000):
                print("[perf]")
                for k,v in self.perfTimer.items():
                    print('% 15s: [% 5.4f,% 5.4f,% 5.4f,% 5.4f]'%(k,v[0]/1000000,v[3]/1000000,v[4]/1000000,v[5]/1000000))
                # print("NaN: %f"%(sum(self.perfTimer[13:])/1000000))
                print("\n")
                if self.statPerf==2:
                    self.statPerfTimer=self.tNow
                else:
                    self.statPerf = 0
            await asyncio.sleep(0)

    async def doEvents(self):
        tasks=[]
        tasks.append(asyncio.create_task(self.doTime()))
        tasks.append(asyncio.create_task(self.doSerial()))
        tasks.append(asyncio.create_task(self.tExaust.tempMeasure()))
        tasks.append(asyncio.create_task(self.tReservoir.tempMeasure()))
        tasks.append(asyncio.create_task(self.tAmbient.tempMeasure()))
        #tasks.append(asyncio.create_task(self.doTemps()))
        # tasks.append(asyncio.create_task(self.doEvents2()))
        tasks.append(asyncio.create_task(self.setExaust()))
        tasks.append(asyncio.create_task(self.setPump()))
        tasks.append(asyncio.create_task(self.setValve()))
        tasks.append(asyncio.create_task(self.setPeltier()))
        tasks.append(asyncio.create_task(self.setTemp()))
        tasks.append(asyncio.create_task(self.doEncoder()))
        tasks.append(asyncio.create_task(self.doDisplay()))
        tasks.append(asyncio.create_task(self.doPerfStat()))
        await asyncio.gather(*tasks)
        # tasks.append(asyncio.create_task(self.setPeltier()))
        # tasks.append(asyncio.create_task(self.setTemp()))
        # tasks.append(asyncio.create_task(self.doEncoder()))
        await asyncio.sleep(0)
async def main():
    # inA=AnalogIn(board.A3)
    tempC=tempController()
    await tempC.init()
    await tempC.doEvents()
    # while True:
    #     await asyncio.sleep(0)

asyncio.run(main())

