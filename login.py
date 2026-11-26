"""
login.py - 芯位平台登录认证模块
"""

import json
import time
import hashlib
import random
import logging
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode
import requests

logger = logging.getLogger(__name__)


class BeeLineAuth:
    """蜂线平台认证"""
    
    BASE_URL = "https://www.beeline-ai.com"
    TOKEN_URL = "/api/xinwei-auth/oauth2/token"
    CLIENT_ID = "xinwei"
    CLIENT_SECRET = "123456"
    
    def __init__(self):
        self.session = requests.Session()
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expiry: float = 0
        self.user_info: Dict = {}
        self._init_session()
    
    def _init_session(self):
        """初始化会话"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'language': 'zh',
            'Origin': self.BASE_URL,
            'Referer': f'{self.BASE_URL}/',
        })
        
        device_id = hashlib.md5(f"{time.time()}{random.random()}".encode()).hexdigest()
        self.session.cookies.set('deviceId', device_id, domain='.beeline-ai.com')
        self.session.cookies.set('language', 'zh', domain='.beeline-ai.com')
        self.session.cookies.set('theme', 'light', domain='.beeline-ai.com')
        
        try:
            self.session.get(self.BASE_URL, timeout=10)
        except:
            pass
    
    @staticmethod
    def md5(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()
    
    def login(self, username: str, password: str, encrypt: bool = True) -> Tuple[bool, str]:
        """账号密码登录"""
        if encrypt and len(password) != 32:
            password = self.md5(password)
        
        data = {
            "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "grant_type": "password",
            "scope": "all",
            "username": username,
            "password": password,
            "type": "SSO",
            "platform_type": "XINWEI_HOME",
            "captchaVerification": "",
        }
        
        try:
            resp = self.session.post(
                f"{self.BASE_URL}{self.TOKEN_URL}",
                data=urlencode(data),
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=15
            )
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get('code') == 200 or 'access_token' in result:
                    self._process_response(resp, result)
                    return True, "登录成功"
                return False, result.get('msg', '登录失败')
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)
    
    def login_with_token(self, token: str) -> Tuple[bool, str]:
        """使用Token登录"""
        self.access_token = token
        self.session.cookies.set('Authorization', token, domain='.beeline-ai.com')
        self.session.cookies.set('Authorization', token, domain='www.beeline-ai.com')
        self.session.headers['Authorization'] = f'Bearer {token}'
        
        if self._test_token():
            return True, "Token有效"
        return False, "Token无效"
    
    def _process_response(self, response, result_data: Dict):
        """处理登录响应"""
        token_data = result_data.get('data', result_data)
        if isinstance(token_data, str):
            try:
                token_data = json.loads(token_data)
            except:
                pass
        
        self.access_token = token_data.get('access_token') or result_data.get('access_token')
        self.refresh_token = token_data.get('refresh_token') or result_data.get('refresh_token')
        
        if self.access_token:
            self.session.headers['Authorization'] = f'Bearer {self.access_token}'
            expires_in = token_data.get('expires_in', 86400)
            try:
                expires_in = int(float(expires_in))
            except (ValueError, TypeError):
                expires_in = 86400
            self.token_expiry = time.time() + expires_in
            logger.info(f"✅ Token获取成功，有效期: {expires_in}秒")
        
        user_data = token_data.get('user', token_data.get('userInfo', token_data))
        if isinstance(user_data, dict):
            self.user_info = user_data
    
    def _test_token(self) -> bool:
        """测试Token有效性"""
        try:
            resp = self.session.post(
                f"{self.BASE_URL}/api/learning-service/admin/studentLearning/getChapterData",
                json={"teachingClassId": "test"},
                timeout=10
            )
            return resp.status_code in [200, 400]
        except:
            return False
    
    def get_cookies_dict(self) -> Dict[str, str]:
        return {c.name: c.value for c in self.session.cookies}
    
    def get_session(self) -> requests.Session:
        return self.session
    
    def save_session(self, filepath: str = "session.json"):
        """保存会话"""
        data = {
            'cookies': self.get_cookies_dict(),
            'headers': dict(self.session.headers),
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'token_expiry': self.token_expiry,
            'user_info': self.user_info,
            'timestamp': time.time()
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 会话已保存: {filepath}")
    
    def load_session(self, filepath: str = "session.json") -> bool:
        """加载会话"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for name, value in data.get('cookies', {}).items():
                self.session.cookies.set(name, value)
            
            self.access_token = data.get('access_token')
            self.refresh_token = data.get('refresh_token')
            self.token_expiry = data.get('token_expiry', 0)
            self.user_info = data.get('user_info', {})
            
            if data.get('headers'):
                for name, value in data['headers'].items():
                    if name not in ['Content-Type', 'Content-Length']:
                        self.session.headers[name] = value
            
            if self.access_token:
                self.session.headers['Authorization'] = f'Bearer {self.access_token}'
            
            logger.info(f"📂 会话已加载: {filepath}")
            return self._test_token()
        except FileNotFoundError:
            return False
        except Exception as e:
            logger.error(f"加载失败: {e}")
            return False