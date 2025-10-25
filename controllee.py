from protocol_base import ProtocolBase
from twisted.internet import reactor
from mss import mss
import io
import PIL
import PIL.Image
import json
from constants import *
import commands
import threading
import numpy as np
import zlib
import struct
import time

class ControlleeProtocol(ProtocolBase):
    def __init__(self):
        ProtocolBase.__init__(self)
        print("Controllee init")
        self.config = {}
        self.last_screenshot_time = 0
        self.screenshot_interval = 1.0 / VAR_FPS_DEFAULT  # Default 120 FPS
        self.screenshot_lock = threading.Lock()
        self.is_processing_screenshot = False

        self.setVariable(VAR_SCALE, VAR_SCALE_DEFAULT, False)
        self.setVariable(VAR_MONITOR, VAR_MONITOR_DEFAULT, False)
        self.setVariable(VAR_SHOULD_UPDATE_COMMANDS, VAR_SHOULD_UPDATE_COMMANDS_DEFAULT, False)
        self.setVariable(VAR_FPS, VAR_FPS_DEFAULT, False)
        self.setVariable(VAR_JPEG_QUALITY, VAR_JPEG_QUALITY_DEFAULT, False)
        self.setVariable(VAR_USE_NUMPY, VAR_USE_NUMPY_DEFAULT, False)
        self.setVariable(VAR_COMPRESSION_LEVEL, VAR_COMPRESSION_LEVEL_DEFAULT, False)
        self.printConfig()

        reactor.callLater(0.001, self.sendScreenshot)  # Start immediately
        self.commands = commands.Commands(self.config)
        self.commands.start()

    def messageReceived(self, data: bytes):
        decoded = data.decode('ascii')
        if decoded == COMMAND_SEND_SCREENSHOT:
            self.sendScreenshot()
        if decoded.startswith(COMMAND_SET_VAR):
            commandInfo = json.loads(decoded[len(COMMAND_SET_VAR):])
            self.setVariable(**commandInfo)
        if decoded.startswith(COMMAND_NEW_COMMAND):
            commandInfo = json.loads(decoded[len(COMMAND_NEW_COMMAND):])
            self.commands.addCommand(*commandInfo)

    def setVariable(self, variable, value, shouldPrint = True):
        self.config[variable] = value
        # Update FPS interval when FPS changes
        if variable == VAR_FPS and value > 0:
            self.screenshot_interval = 1.0 / value
        if shouldPrint:
            self.printConfig()

    def printConfig(self):
        print(self.config)

    def sendScreenshot(self):
        current_time = time.time()
        
        # Prevent overlapping screenshot processing for high FPS
        with self.screenshot_lock:
            if self.is_processing_screenshot:
                next_delay = 0.001
                reactor.callLater(next_delay, self.sendScreenshot)
                return
            
            # Only send screenshot if enough time has passed based on FPS setting
            if current_time - self.last_screenshot_time >= self.screenshot_interval:
                self.is_processing_screenshot = True
                self.last_screenshot_time = current_time
                
                try:
                    # Intelligent method selection
                    fps_target = self.config.get(VAR_FPS, VAR_FPS_DEFAULT)
                    use_numpy = self.config.get(VAR_USE_NUMPY, VAR_USE_NUMPY_DEFAULT)
                    scale = self.config.get(VAR_SCALE, VAR_SCALE_DEFAULT)
                    
                    # Smart selection based on resolution and FPS
                    if use_numpy and scale <= 0.5 and fps_target >= 90:
                        # Low resolution + high FPS: numpy might be better
                        self.sendScreenshotNumpy()
                    else:
                        # Default to optimized JPEG (generally faster)
                        self.sendScreenshotJPEG()
                finally:
                    self.is_processing_screenshot = False
        
        # Ultra-aggressive scheduling for maximum FPS
        next_delay = max(0.005, self.screenshot_interval * 0.8)  # More conservative to prevent flicker
        reactor.callLater(next_delay, self.sendScreenshot)

    def sendScreenshotNumpy(self):
        """Ultra-fast numpy-based screenshot transmission"""
        with mss() as sct:
            monitorRequest = self.config[VAR_MONITOR]
            monitorRequest = min(len(sct.monitors) - 1, monitorRequest)
            
            # Grab screenshot as numpy array directly
            ss = sct.grab(sct.monitors[monitorRequest])
            
            # Convert directly to numpy with optimized view operations
            img_array = np.frombuffer(ss.bgra, dtype=np.uint8).reshape((ss.height, ss.width, 4))
            
            # Ultra-fast BGR to RGB conversion using slicing (no copying)
            rgb_array = img_array[:, :, [2, 1, 0]]  # BGR to RGB, drop alpha
            
            # Apply scaling with ultra-fast method
            if self.config[VAR_SCALE] < 1:
                scale = self.config[VAR_SCALE]
                
                # Use numpy's array slicing for lightning-fast downsampling
                step = max(1, int(1/scale))
                rgb_array = rgb_array[::step, ::step]
            
            # Adaptive compression based on FPS target
            fps_target = self.config.get(VAR_FPS, VAR_FPS_DEFAULT)
            if fps_target > 100:
                # Ultra-high FPS: minimal compression for speed
                compression_level = 1
                # Send raw data for maximum speed at very high FPS
                header = struct.pack('<III', rgb_array.shape[0], rgb_array.shape[1], rgb_array.shape[2])
                array_bytes = rgb_array.tobytes()
                message_data = b'NUMPY' + header + array_bytes  # No compression for ultra-high FPS
            else:
                # High FPS: balanced compression
                compression_level = self.config.get(VAR_COMPRESSION_LEVEL, VAR_COMPRESSION_LEVEL_DEFAULT)
                header = struct.pack('<III', rgb_array.shape[0], rgb_array.shape[1], rgb_array.shape[2])
                array_bytes = rgb_array.tobytes()
                compressed_data = zlib.compress(array_bytes, compression_level)
                message_data = b'NUMPY' + header + compressed_data
            
            self.writeMessage(message_data)

    def sendScreenshotJPEG(self):
        """Optimized JPEG method for maximum FPS"""
        with io.BytesIO() as output:
            with mss() as sct:
                monitorRequest = self.config[VAR_MONITOR]
                monitorRequest = min(len(sct.monitors) - 1, monitorRequest)
                ss = sct.grab(sct.monitors[monitorRequest])
                
                # Ultra-fast PIL conversion
                ss = PIL.Image.frombytes('RGB', ss.size, ss.bgra, 'raw', 'BGRX')
                
                # Optimized scaling
                if self.config[VAR_SCALE] < 1:
                    new_size = (int(ss.size[0] * self.config[VAR_SCALE]),
                               int(ss.size[1] * self.config[VAR_SCALE]))
                    ss = ss.resize(new_size, PIL.Image.NEAREST)  # NEAREST is fastest
                
                # Adaptive quality based on FPS target
                fps_target = self.config.get(VAR_FPS, VAR_FPS_DEFAULT)
                if fps_target >= 120:
                    quality = 15  # Ultra-low quality for maximum speed
                elif fps_target >= 60:
                    quality = 25  # Low quality for high speed
                else:
                    quality = self.config.get(VAR_JPEG_QUALITY, VAR_JPEG_QUALITY_DEFAULT)
                
                # Ultra-fast JPEG encoding
                ss.save(output, format="JPEG", quality=quality, optimize=False)
                self.writeMessage(output.getvalue())
    
    def connectionLost(self, reason):
        self.commands.shouldRun = False
