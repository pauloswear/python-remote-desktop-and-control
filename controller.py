from protocol_base import ProtocolBase
import tkinter
from twisted.internet import tksupport, reactor
import hashlib
from PIL import ImageTk, Image
from io import BytesIO
from constants import *
import json
import time
import numpy as np
import zlib
import struct

class FactoryControllerBase:
    def __init__(self):
        self.tk = tkinter.Tk()
        tksupport.install(self.tk)

    def buildProtocol(self, addr):
        return ControllerProtocol(self.tk)


class ControllerProtocol(ProtocolBase):
    def __init__(self, tk):
        ProtocolBase.__init__(self)

        print("Controller init")
        self.root = tkinter.Toplevel(tk)
        self.root.state('zoomed')
        self.root.protocol("WM_DELETE_WINDOW", self.onCloseClicked)
        self.lastReceivedTime = time.time()

        frame = tkinter.Frame(self.root)
        frame.pack()

        tkinter.Label(frame, text='Monitor:').pack(side=tkinter.LEFT)
        monScale = tkinter.Scale(frame, from_=0, to=4, orient=tkinter.HORIZONTAL, command=self.changeMonitor)
        monScale.pack(side=tkinter.LEFT)
        monScale.set(VAR_MONITOR_DEFAULT)

        tkinter.Label(frame, text='Scale:').pack(side=tkinter.LEFT)
        scaleScale = tkinter.Scale(frame, from_=0.1, to=1, orient=tkinter.HORIZONTAL, resolution=0.1, command=self.changeScale)
        scaleScale.pack(side=tkinter.LEFT)
        scaleScale.set(VAR_SCALE_DEFAULT)

        tkinter.Label(frame, text='FPS:').pack(side=tkinter.LEFT)
        fpsScale = tkinter.Scale(frame, from_=30, to=144, orient=tkinter.HORIZONTAL, command=self.changeFPS)
        fpsScale.pack(side=tkinter.LEFT)
        fpsScale.set(VAR_FPS_DEFAULT)

        tkinter.Label(frame, text='Quality:').pack(side=tkinter.LEFT)
        qualityScale = tkinter.Scale(frame, from_=10, to=95, orient=tkinter.HORIZONTAL, command=self.changeQuality)
        qualityScale.pack(side=tkinter.LEFT)
        qualityScale.set(VAR_JPEG_QUALITY_DEFAULT)

        self.numpyVar = tkinter.BooleanVar(self.root, VAR_USE_NUMPY_DEFAULT)
        numpyCheck = tkinter.Checkbutton(frame, text='Numpy Mode', command=self.changeNumpyMode, variable=self.numpyVar)
        numpyCheck.pack(side=tkinter.LEFT)

        tkinter.Label(frame, text='Compression:').pack(side=tkinter.LEFT)
        compressionScale = tkinter.Scale(frame, from_=1, to=9, orient=tkinter.HORIZONTAL, command=self.changeCompression)
        compressionScale.pack(side=tkinter.LEFT)
        compressionScale.set(VAR_COMPRESSION_LEVEL_DEFAULT)

        self.updateVar = tkinter.BooleanVar(self.root, VAR_SHOULD_UPDATE_COMMANDS_DEFAULT)
        updateCheck = tkinter.Checkbutton(frame, text='Update commands', command=self.changeUpdateCommands, variable=self.updateVar)
        updateCheck.pack(side=tkinter.LEFT)

        tkinter.Label(frame, text='FPS:').pack(side=tkinter.LEFT)
        self.fpsLabel = tkinter.Label(frame, text='?')
        self.fpsLabel.pack(side=tkinter.LEFT)

        self.label = tkinter.Label(self.root)
        self.label.pack(fill=tkinter.BOTH, expand=True)
        # self.label.bind('<Motion>', self.onMouseMoved)
        self.root.bind('<Key>', self.onKeyDown)
        self.root.bind('<KeyRelease>', self.onKeyUp)
        self.label.bind('<Button>', self.onMouseDown)
        self.label.bind('<ButtonRelease>', self.onMouseUp)
        self.label.bind('<MouseWheel>', self.onMouseWheel)
    
    def changeScale(self, newScale: str):
        self.setValue(VAR_SCALE, float(newScale))
    
    def changeMonitor(self, newMonitor: str):
        self.setValue(VAR_MONITOR, int(newMonitor))
    
    def changeFPS(self, newFPS: str):
        self.setValue(VAR_FPS, int(newFPS))
    
    def changeQuality(self, newQuality: str):
        self.setValue(VAR_JPEG_QUALITY, int(newQuality))
    
    def changeNumpyMode(self):
        self.setValue(VAR_USE_NUMPY, self.numpyVar.get())
    
    def changeCompression(self, newCompression: str):
        self.setValue(VAR_COMPRESSION_LEVEL, int(newCompression))
    
    def changeUpdateCommands(self):
        self.setValue(VAR_SHOULD_UPDATE_COMMANDS, self.updateVar.get())
    
    def setValue(self, variable, value):
        toSend = COMMAND_SET_VAR.encode('ascii')
        toSend += json.dumps({
            'variable': variable,
            'value': value
        }).encode('ascii')
        self.writeMessage(toSend)
    
    def sendCommand(self, commandName, *args):
        toSend = COMMAND_NEW_COMMAND.encode('ascii')
        toSend += json.dumps([commandName, *args]).encode('ascii')
        self.writeMessage(toSend)

    def getLocalPosition(self, x, y):
        labelSize = self.getLabelSize()
        return (x / labelSize[0], y / labelSize[1])

    def onMouseMoved(self, event):
        print(event.x, event.y)
    
    def sendMouseEvent(self, event, isDown: bool):
        location = self.getLocalPosition(event.x, event.y)
        self.sendCommand('MoveMouse', location[0], location[1])
        self.sendCommand('MouseInput', event.num == 1, isDown)

    def onMouseDown(self, event):
        self.sendMouseEvent(event, True)

    def onMouseUp(self, event):
        self.sendMouseEvent(event, False)
    
    def onMouseWheel(self, event):
        location = self.getLocalPosition(event.x, event.y)
        # event.delta is the scroll amount (positive = up, negative = down)
        scroll_direction = 1 if event.delta > 0 else -1
        scroll_amount = abs(event.delta) // 120  # Normalize scroll amount
        self.sendCommand('ScrollMouse', location[0], location[1], scroll_direction, scroll_amount)
    
    def sendKeyEvent(self, event, isDown: bool):
        self.sendCommand('KeyboardInput', event.keycode, isDown)
    
    def onKeyDown(self, event):
        self.sendKeyEvent(event, True)
    
    def onKeyUp(self, event=None):
        self.sendKeyEvent(event, False)

    def onCloseClicked(self):
        self.transport.abortConnection()
        reactor.stop()

    def getLabelSize(self):
        return (self.label.winfo_width(), self.label.winfo_height())

    def messageReceived(self, data: bytes):
        try:
            current_time = time.time()
            
            # Check if this is numpy data
            if data.startswith(b'NUMPY'):
                self.processNumpyData(data[5:])  # Remove 'NUMPY' prefix
            else:
                self.processJPEGData(data)
            
            # Update FPS counter
            if hasattr(self, 'lastReceivedTime'):
                fps = 1.0 / (current_time - self.lastReceivedTime)
                self.fpsLabel['text'] = f'{fps:.1f}'
            self.lastReceivedTime = current_time
            
            # Request next screenshot immediately for maximum FPS
            self.writeMessage(COMMAND_SEND_SCREENSHOT.encode('ascii'))
        except Exception as e:
            print(f"Error processing image: {e}")
            # Request next screenshot even on error
            self.writeMessage(COMMAND_SEND_SCREENSHOT.encode('ascii'))

    def processNumpyData(self, data: bytes):
        """Process numpy array data (compressed or uncompressed)"""
        try:
            # Read header (height, width, channels)
            header_size = struct.calcsize('<III')
            if len(data) < header_size:
                return
            
            height, width, channels = struct.unpack('<III', data[:header_size])
            payload_data = data[header_size:]
            
            # Calculate expected size for uncompressed data
            expected_size = height * width * channels
            
            # Determine if data is compressed or raw
            if len(payload_data) == expected_size:
                # Raw uncompressed data (ultra-high FPS mode)
                array_bytes = payload_data
            else:
                # Compressed data
                array_bytes = zlib.decompress(payload_data)
            
            # Reconstruct numpy array with optimized operations
            img_array = np.frombuffer(array_bytes, dtype=np.uint8).reshape((height, width, channels))
            
            # Convert numpy array to PIL Image (fastest method)
            img = Image.fromarray(img_array, 'RGB')
            
            # Resize to fit label with fastest method
            newSize = self.getLabelSize()
            if newSize[0] > 0 and newSize[1] > 0:
                img = img.resize(newSize, Image.NEAREST)  # NEAREST is fastest
                self.currentImage = ImageTk.PhotoImage(img)
                self.label.configure(image=self.currentImage)
                
        except Exception as e:
            print(f"Error processing numpy data: {e}")

    def processJPEGData(self, data: bytes):
        """Process JPEG image data (fallback)"""
        try:
            newSize = self.getLabelSize()
            if newSize[0] > 0 and newSize[1] > 0:
                img = Image.open(BytesIO(data))
                img = img.resize(newSize, Image.NEAREST)
                self.currentImage = ImageTk.PhotoImage(img)
                self.label.configure(image=self.currentImage)
        except Exception as e:
            print(f"Error processing JPEG data: {e}")

    def connectionLost(self, reason):
        print('Connection lost', reason)
        ProtocolBase.connectionLost(self)
        if self.root is not None:
            self.root.destroy()
            self.root = None