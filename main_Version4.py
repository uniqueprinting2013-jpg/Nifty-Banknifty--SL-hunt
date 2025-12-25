# main.py
import threading
import queue
import time
import json
import os
import traceback
from datetime import datetime, time as dtime, date

import requests

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label

# ============================================================
# GLOBAL CONFIG
# ============================================================
REFRESH_SEC = 60          # ⚠ DO NOT REDUCE
MIN_DELTA = 10000

PCR_UPPER = 1.10
PCR_LOWER = 0.90

# ============================================================
# PSYCHOLOGICAL MEMORY
# ============================================================
PSY_PATTERNS = [0, 200, 400, 500, 600, 800]
PSY_ATTEMPTS = {"NIFTY": {}, "BANKNIFTY": {}}
PSY_ACCEPTANCE = {"NIFTY": {}, "BANKNIFTY": {}}

# ============================================================
# PRICE + OI MEMORY
# ============================================================
PRICE_MEMORY = {}
OI_MEMORY = {
    "NIFTY": {"CE": {}, "PE": {}},
    "BANKNIFTY": {"CE": {}, "PE": {}}
}

# ============================================================
# INDEX CONFIG
# ============================================================
INDEXES = {
    "NIFTY": {
        "symbol": "NIFTY",
        "step": 50,
        "range": 5,
        "cache": "nifty_cache.json"
    },
    "BANKNIFTY": {
        "symbol": "BANKNIFTY",
        "step": 100,
        "range": 5,
        "cache": "banknifty_cache.json"
    }
}

# ============================================================
# NSE SESSION
# ============================================================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/option-chain"
}

session = requests.Session()
session.headers.update(HEADERS)

# ============================================================
# TIME HELPERS
# ============================================================
def market_open():
    return dtime(9, 15) <= datetime.now().time() <= dtime(15, 30)

def reset_cache_if_new_day(cache):
    if os.path.exists(cache):
        if datetime.fromtimestamp(os.path.getmtime(cache)).date() != date.today():
            try:
                os.remove(cache)
            except Exception:
                pass

# ============================================================
# PSY LEVELS
# ============================================================
def nearest_psy_level(price):
    base = int(price // 1000) * 1000
    levels = [base + p for p in PSY_PATTERNS] + [base + 1000 + p for p in PSY_PATTERNS]
    return min(levels, key=lambda x: abs(price - x))

def record_psy_attempt(index, level):
    bucket = int(time.time() // 300)  # 5-min bucket
    key = (level, bucket)
    PSY_ATTEMPTS[index][key] = PSY_ATTEMPTS[index].get(key, 0) + 1
    return PSY_ATTEMPTS[index][key]

def check_acceptance(index, level, price, step):
    mem = PSY_ACCEPTANCE[index]
    now = time.time()

    if abs(price - level) > step:
        mem.pop(level, None)
        return False

    if level not in mem:
        mem[level] = now
        return False

    return (now - mem[level]) >= 300

# ============================================================
# ATM DELTA OI (pandas removed)
# ============================================================
def atm_delta_oi(index, rows, atm):
    # rows: list of dicts with keys STRIKE, CE_OI, PE_OI
    row = next((r for r in rows if r["STRIKE"] == atm), None)
    if not row:
        return 0, 0

    try:
        ce_oi = int(row.get("CE_OI", 0))
    except Exception:
        ce_oi = 0
    try:
        pe_oi = int(row.get("PE_OI", 0))
    except Exception:
        pe_oi = 0

    prev_ce = OI_MEMORY[index]["CE"].get(atm, ce_oi)
    prev_pe = OI_MEMORY[index]["PE"].get(atm, pe_oi)

    ce_delta = ce_oi - prev_ce
    pe_delta = pe_oi - prev_pe

    OI_MEMORY[index]["CE"][atm] = ce_oi
    OI_MEMORY[index]["PE"][atm] = pe_oi

    return ce_delta, pe_delta

# ============================================================
# FETCH OPTION CHAIN
# ============================================================
def fetch_chain(cfg, logger):
    reset_cache_if_new_day(cfg["cache"])

    if market_open():
        try:
            # warm up
            session.get("https://www.nseindia.com", timeout=5)
            time.sleep(1)

            url = f"https://www.nseindia.com/api/option-chain-indices?symbol={cfg['symbol']}"
            r = session.get(url, timeout=10)

            if r.status_code == 200:
                data = r.json()
                with open(cfg["cache"], "w") as f:
                    json.dump(data, f)
                return data, "LIVE"
        except Exception as e:
            logger(f"Live fetch failed: {e}")

    if os.path.exists(cfg["cache"]):
        try:
            with open(cfg["cache"]) as f:
                return json.load(f), "CACHED"
        except Exception as e:
            logger(f"Cache read failed: {e}")

    return None, "NO_DATA"

# ============================================================
# PROCESS INDEX (pandas removed)
# ============================================================
def process_index(cfg, logger):
    data, mode = fetch_chain(cfg, logger)
    if not data:
        return {"mode": "NO_DATA"}

    spot = data["records"].get("underlyingValue", 0)
    atm = round(spot / cfg["step"]) * cfg["step"]

    rows = []
    for r in data["records"].get("data", []):
        sp = r.get("strikePrice")
        if sp is None:
            continue
        if atm - cfg["range"] * cfg["step"] <= sp <= atm + cfg["range"] * cfg["step"]:
            rows.append({
                "STRIKE": sp,
                "CE_OI": r.get("CE", {}).get("openInterest", 0),
                "CE_LTP": r.get("CE", {}).get("lastPrice", 0),
                "PE_OI": r.get("PE", {}).get("openInterest", 0),
                "PE_LTP": r.get("PE", {}).get("lastPrice", 0),
            })

    if not rows:
        return {"mode": "NO_DATA"}

    # full CE/PE from full dataset (not only sliced rows)
    full_ce = sum(r.get("CE", {}).get("openInterest", 0) for r in data["records"].get("data", []))
    full_pe = sum(r.get("PE", {}).get("openInterest", 0) for r in data["records"].get("data", []))
    pcr = round(full_pe / full_ce, 2) if full_ce else 0

    ce_d, pe_d = atm_delta_oi(cfg["symbol"], rows, atm)

    # return rows sorted by strike under key "df" for compatibility with UI code
    rows_sorted = sorted(rows, key=lambda x: x["STRIKE"])

    return {
        "df": rows_sorted,
        "spot": spot,
        "atm": atm,
        "pcr": pcr,
        "ce_delta": ce_d,
        "pe_delta": pe_d,
        "mode": mode
    }

# ============================================================
# BIAS LOGIC
# ============================================================
def pcr_bias(pcr):
    if pcr > PCR_UPPER:
        return "BULLISH"
    if pcr < PCR_LOWER:
        return "BEARISH"
    return None

def combined_bias(nifty, bank):
    nb = pcr_bias(nifty.get("pcr", 0))
    bb = pcr_bias(bank.get("pcr", 0))

    if not nb or not bb:
        return None, "Neutral PCR"

    if nb != bb:
        return None, "Index divergence"

    return nb, "Market aligned"

# ============================================================
# SL HUNT LOGIC
# ============================================================
def psychological_trap(index, res):
    price = res["spot"]
    psy = nearest_psy_level(price)
    step = INDEXES[index]["step"]

    bias = pcr_bias(res["pcr"])
    if not bias:
        return "WAIT", "PCR neutral", 0

    if abs(price - psy) > step * 0.6:
        return "WAIT", "Away from psy", 0

    if not check_acceptance(index, psy, price, step):
        return "WAIT", "Accepting psy", 0

    if record_psy_attempt(index, psy) < 2:
        return "WAIT", "First attempt", 0

    if bias == "BEARISH" and res["ce_delta"] > MIN_DELTA and res["pe_delta"] < 0:
        return "BUY PE", f"CE TRAP @ {psy}", 75

    if bias == "BULLISH" and res["pe_delta"] > MIN_DELTA and res["ce_delta"] < 0:
        return "BUY CE", f"PE TRAP @ {psy}", 75

    return "WAIT", "No confirmation", 0

# ============================================================
# ENGINE THREAD
# ============================================================
class EngineThread(threading.Thread):
    def __init__(self, log_queue, refresh_sec=REFRESH_SEC):
        super().__init__(daemon=True)
        self.log_queue = log_queue
        self.refresh_sec = refresh_sec
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            while not self._stop_event.is_set():
                try:
                    now = datetime.now()
                    out_lines = []
                    out_lines.append("🚀 INSTITUTIONAL SL HUNT ENGINE v2.3.1")
                    out_lines.append("TIME: " + str(now))

                    nifty = process_index(INDEXES["NIFTY"], self._log)
                    bank  = process_index(INDEXES["BANKNIFTY"], self._log)

                    market_bias, bias_reason = combined_bias(nifty, bank)

                    out_lines.append("")
                    out_lines.append("📈 MARKET BIAS")
                    out_lines.append("STATUS : " + (market_bias if market_bias else "NEUTRAL"))
                    out_lines.append("REASON : " + bias_reason)

                    if market_bias and "df" in bank:
                        action, reason, score = psychological_trap("BANKNIFTY", bank)
                    else:
                        action, reason, score = "WAIT", bias_reason, 0

                    out_lines.append("")
                    out_lines.append("🎯 FINAL SIGNAL")
                    out_lines.append("ACTION     : " + action)
                    out_lines.append("REASON     : " + reason)
                    out_lines.append("CONFIDENCE : " + str(score))

                    out_lines.append("")
                    out_lines.append("Next refresh in {} sec…".format(self.refresh_sec))

                    self.log_queue.put("\n".join(out_lines))

                except Exception as e:
                    tb = traceback.format_exc()
                    self.log_queue.put("Engine error:\n" + str(e) + "\n" + tb)

                # wait with ability to stop early
                if self._stop_event.wait(self.refresh_sec):
                    break
        except Exception as e:
            self.log_queue.put("Fatal engine thread error: " + str(e))

    def _log(self, msg):
        # send small log messages to main UI
        self.log_queue.put("[LOG] " + str(msg))


# ============================================================
# Kivy UI
# ============================================================
class MainLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=6, padding=6, **kwargs)
        top = BoxLayout(size_hint_y=None, height='40dp', spacing=6)
        self.status = Label(text="Stopped", size_hint_x=0.4)
        self.time_lbl = Label(text="", size_hint_x=0.6)
        top.add_widget(self.status)
        top.add_widget(self.time_lbl)

        self.log_view = TextInput(text="", readonly=True, font_name='Roboto', size_hint_y=1)
        self.log_view.cursor = (0, 0)
        self.log_view.multiline = True

        buttons = BoxLayout(size_hint_y=None, height='48dp', spacing=6)
        self.start_btn = Button(text="Start", on_press=self.on_start)
        self.stop_btn = Button(text="Stop", on_press=self.on_stop, disabled=True)
        buttons.add_widget(self.start_btn)
        buttons.add_widget(self.stop_btn)

        self.add_widget(top)
        self.add_widget(self.log_view)
        self.add_widget(buttons)

        # log queue and engine thread
        self.log_queue = queue.Queue()
        self.engine = None
        Clock.schedule_interval(self._poll_queue, 0.5)
        Clock.schedule_interval(self._update_time, 1.0)

    def _update_time(self, dt):
        self.time_lbl.text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _poll_queue(self, dt):
        updated = False
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            else:
                # append to TextInput
                cur = self.log_view.text
                if cur:
                    cur = cur + "\n\n" + msg
                else:
                    cur = msg
                # keep last ~12000 chars
                if len(cur) > 12000:
                    cur = cur[-12000:]
                self.log_view.text = cur
                # move cursor to end
                try:
                    self.log_view.cursor = (len(self.log_view.text), 0)
                except Exception:
                    pass
                updated = True

        if updated:
            # ensure scroll to bottom by setting focus briefly
            self.log_view.focus = False

    def on_start(self, instance):
        if self.engine and self.engine.is_alive():
            return
        self.engine = EngineThread(self.log_queue, refresh_sec=REFRESH_SEC)
        self.engine.start()
        self.status.text = "Running"
        self.start_btn.disabled = True
        self.stop_btn.disabled = False
        self.log_queue.put("[SYSTEM] Engine started")

    def on_stop(self, instance):
        if self.engine:
            self.engine.stop()
            self.engine.join(timeout=5)
        self.status.text = "Stopped"
        self.start_btn.disabled = False
        self.stop_btn.disabled = True
        self.log_queue.put("[SYSTEM] Engine stopped")


class SLHuntApp(App):
    def build(self):
        Window.clearcolor = (1, 1, 1, 1)
        layout = MainLayout()
        return layout

    def on_stop(self):
        # ensure engine stopped when app exits
        root = self.root
        if root and root.engine:
            root.engine.stop()
            root.engine.join(timeout=2)


if __name__ == '__main__':
    SLHuntApp().run()