#!/usr/bin/env python3
"""
Standalone Voice Visualizer
Works without external AI dependencies - focuses on the visualization and interaction
"""

import asyncio
import json
import websockets
import random
import time
from datetime import datetime

class VoiceVisualizerStandalone:
    def __init__(self):
        self.is_listening = False
        self.voice_level = 0
        self.current_status = "Ready"
        self.websocket_clients = set()
        
    async def start_websocket_server(self, host="localhost", port=8765):
        """Start WebSocket server for real-time communication with visualizer"""
        
        async def handle_client(websocket, path):
            print(f"🔗 Visualizer connected from {websocket.remote_address}")
            self.websocket_clients.add(websocket)
            
            try:
                async for message in websocket:
                    data = json.loads(message)
                    await handle_visualizer_message(data, websocket)
            except websockets.exceptions.ConnectionClosed:
                print("🔌 Visualizer disconnected")
            finally:
                self.websocket_clients.remove(websocket)
        
        async def handle_visualizer_message(data, websocket):
            """Handle messages from the web visualizer"""
            
            if data["type"] == "start_listening":
                await self.start_voice_detection()
                await self.broadcast_to_visualizers({
                    "type": "status_update",
                    "message": "🎧 Voice detection started",
                    "color": "#4CC9F0"
                })
                
            elif data["type"] == "stop_listening":
                await self.stop_voice_detection()
                await self.broadcast_to_visualizers({
                    "type": "status_update", 
                    "message": "⏹️ Voice detection stopped",
                    "color": "#FFD166"
                })
                
            elif data["type"] == "test_scam":
                await self.simulate_scam_detection()
                
            elif data["type"] == "test_legitimate":
                await self.simulate_legitimate_call()
                
            elif data["type"] == "voice_level":
                self.voice_level = data["level"]
                if self.voice_level > 70:
                    await self.trigger_glitch_effect()
        
        self.server = await websockets.serve(handle_client, host, port)
        print(f"🌐 Voice Visualizer WebSocket server started on ws://{host}:{port}")
        
    async def broadcast_to_visualizers(self, data):
        """Send data to all connected visualizer clients"""
        if self.websocket_clients:
            message = json.dumps(data)
            await asyncio.gather(
                *[client.send(message) for client in self.websocket_clients],
                return_exceptions=True
            )
    
    async def start_voice_detection(self):
        """Start voice activity detection (simulated)"""
        self.is_listening = True
        print("🎤 Starting simulated voice detection...")
        
        # Simulate voice detection with real-time updates
        while self.is_listening:
            # Simulate varying voice levels
            voice_level = random.randint(0, 100)
            
            await self.broadcast_to_visualizers({
                "type": "voice_level_update",
                "level": voice_level
            })
            
            # Detect patterns and update status
            if voice_level > 80:
                await self.broadcast_to_visualizers({
                    "type": "status_update",
                    "message": "🗣️ Loud voice detected - analyzing...",
                    "color": "#F72585"
                })
            elif voice_level > 50:
                await self.broadcast_to_visualizers({
                    "type": "status_update", 
                    "message": "👂 Voice activity detected",
                    "color": "#4CC9F0"
                })
            
            await asyncio.sleep(0.1)
    
    async def stop_voice_detection(self):
        """Stop voice detection"""
        self.is_listening = False
        print("⏹️ Voice detection stopped")
        
        await self.broadcast_to_visualizers({
            "type": "voice_level_update",
            "level": 0
        })
    
    async def simulate_scam_detection(self):
        """Simulate scam detection for demo"""
        print("🚨 Simulating scam detection...")
        
        await self.broadcast_to_visualizers({
            "type": "status_update",
            "message": "🚨 SCAM DETECTED: 'IRS' impersonation attempt",
            "color": "#F72585"
        })
        
        await self.broadcast_to_visualizers({
            "type": "trigger_alert",
            "alert_type": "scam"
        })
        
        # Simulate voice response
        await self.speak_response("Warning: This call appears to be fraudulent. Authorities will be notified.", "SCAM_DETECTED")
        
        # Log the detection
        await self.log_detection_event("SCAM", "IRS impersonation attempt detected")
    
    async def simulate_legitimate_call(self):
        """Simulate legitimate call detection"""
        print("✅ Simulating legitimate call...")
        
        await self.broadcast_to_visualizers({
            "type": "status_update",
            "message": "✅ LEGITIMATE: Verified client call",
            "color": "#06D6A0"
        })
        
        await self.broadcast_to_visualizers({
            "type": "trigger_alert",
            "alert_type": "legitimate"
        })
        
        # Simulate voice response
        await self.speak_response("Thank you for calling. How can I assist you today?", "LEGITIMATE")
        
        # Log the detection
        await self.log_detection_event("LEGITIMATE", "Verified client call")
    
    async def speak_response(self, text, call_type):
        """Send text-to-speech command with appropriate voice settings"""
        voice_settings = {
            "voice_id": "default",
            "speaking_rate": 0.9 if call_type == "SCAM_DETECTED" else 1.1,
            "pitch": -2 if call_type == "SCAM_DETECTED" else 2,
            "emotion": "firm" if call_type == "SCAM_DETECTED" else "helpful"
        }
        
        await self.broadcast_to_visualizers({
            "type": "speak_response",
            "text": text,
            "voice_settings": voice_settings
        })
        
        print(f"🗣️ Speaking: {text}")
        print(f"🎛️ Voice settings: {voice_settings}")
    
    async def trigger_glitch_effect(self):
        """Trigger glitch effect in visualizer"""
        await self.broadcast_to_visualizers({
            "type": "trigger_glitch"
        })
    
    async def log_detection_event(self, event_type, details):
        """Log detection events for analysis"""
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "details": details,
            "voice_level": self.voice_level
        }
        
        # Save to log file
        with open("voice_detection_log.json", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
        
        print(f"📝 Logged: {event_type} - {details}")
    
    async def run_visualizer_demo(self):
        """Run a complete demo of the visualizer system"""
        print("🎬 Starting voice visualizer demo...")
        
        await self.broadcast_to_visualizers({
            "type": "status_update",
            "message": "🎬 Demo mode activated",
            "color": "#7209B7"
        })
        
        # Demo sequence
        demo_steps = [
            ("Starting voice detection...", "start_listening"),
            ("Simulating normal conversation...", "voice_activity"),
            ("Detecting suspicious pattern...", "suspicious_activity"),
            ("SCAM DETECTED!", "scam_alert"),
            ("Switching to legitimate call...", "legitimate_call"),
            ("Demo complete!", "demo_end")
        ]
        
        for message, step in demo_steps:
            await self.broadcast_to_visualizers({
                "type": "status_update",
                "message": message,
                "color": "#4CC9F0"
            })
            
            if step == "start_listening":
                await self.start_voice_detection()
            elif step == "voice_activity":
                for i in range(10):
                    await self.broadcast_to_visualizers({
                        "type": "voice_level_update",
                        "level": 30 + (i * 5)
                    })
                    await asyncio.sleep(0.2)
            elif step == "suspicious_activity":
                for i in range(5):
                    await self.broadcast_to_visualizers({
                        "type": "voice_level_update", 
                        "level": 70 + (i * 6)
                    })
                    await asyncio.sleep(0.3)
                    await self.trigger_glitch_effect()
            elif step == "scam_alert":
                await self.simulate_scam_detection()
            elif step == "legitimate_call":
                await self.simulate_legitimate_call()
            elif step == "demo_end":
                await self.stop_voice_detection()
            
            await asyncio.sleep(2)
        
        print("✅ Demo complete!")

async def main():
    """Main function to run the voice visualizer"""
    print("🚀 Voice Visualizer Starting...")
    print("=" * 50)
    
    # Initialize the visualizer
    visualizer = VoiceVisualizerStandalone()
    
    # Start WebSocket server
    await visualizer.start_websocket_server()
    
    print("\n📋 Instructions:")
    print("1. Open 'interactive_voice_visualizer.html' in your browser")
    print("2. The visualizer will automatically connect to this server")
    print("3. Use the web controls to test voice detection")
    print("4. Or type 'demo' here to run an automated demo")
    print("5. Type 'quit' to exit")
    print("\n⌨️ Commands: demo, scam, legitimate, start, stop, quit")
    
    # Command interface
    while True:
        try:
            command = input("\n> ").strip().lower()
            
            if command == "quit":
                break
            elif command == "demo":
                await visualizer.run_visualizer_demo()
            elif command == "scam":
                await visualizer.simulate_scam_detection()
            elif command == "legitimate":
                await visualizer.simulate_legitimate_call()
            elif command == "start":
                await visualizer.start_voice_detection()
            elif command == "stop":
                await visualizer.stop_voice_detection()
            else:
                print("❓ Unknown command. Available: demo, scam, legitimate, start, stop, quit")
                
        except KeyboardInterrupt:
            break
    
    print("\n👋 Voice Visualizer shutting down...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
