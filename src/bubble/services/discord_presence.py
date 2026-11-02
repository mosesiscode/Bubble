"""Opt-in Discord Rich Presence bridge. No connection is made unless enabled."""

import queue
import threading
import time


class DiscordPresence:
    def __init__(self, client_id):
        self.client_id = str(client_id or '').strip()
        self.events = queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self._run, daemon=True, name='BubbleDiscordPresence')
        self.thread.start()

    def update(self, title, artist, playing, position_ms=0, duration_ms=0):
        event = (str(title or 'Music'), str(artist or 'Bubble Player'), bool(playing), int(position_ms), int(duration_ms))
        try:
            while True: self.events.get_nowait()
        except queue.Empty:
            pass
        try: self.events.put_nowait(event)
        except queue.Full: pass

    def stop(self):
        try:
            while True: self.events.get_nowait()
        except queue.Empty:
            pass
        try: self.events.put_nowait(None)
        except queue.Full: pass

    def _run(self):
        if not self.client_id: return
        try:
            from pypresence import Presence
            rpc = Presence(self.client_id)
            rpc.connect()
        except Exception:
            return
        last_event = None
        last_update = 0.0
        while True:
            try: event = self.events.get(timeout=1)
            except queue.Empty: continue
            if event is None:
                try: rpc.clear(); rpc.close()
                except Exception: pass
                return
            if event == last_event and time.monotonic() - last_update < 15:
                continue
            title, artist, playing, position, duration = event
            try:
                options = {'details': title[:128], 'state': artist[:128], 'large_text': 'Bubble Player', 'activity_type': 2}
                if playing:
                    start = int(time.time() - max(0, position) / 1000)
                    options['start'] = start
                    if duration > 0: options['end'] = start + int(duration / 1000)
                rpc.update(**options)
                last_event = event
                last_update = time.monotonic()
            except Exception:
                # Discord may be closed or temporarily unavailable; retry on the next update.
                last_event = None
