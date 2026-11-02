"""Persistent macOS Keychain storage; secret never appears in argv or files."""
import ctypes,hashlib
from pathlib import Path

class CredentialError(RuntimeError):pass

class KeychainVault:
    def __init__(self,root):
        self.service=b'local-video-agent.notion'
        self.account=('workspace-'+hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:24]).encode()
        self.sec=ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.cf=ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        V=ctypes.c_void_p;U=ctypes.c_uint32;P=ctypes.POINTER
        self.sec.SecKeychainFindGenericPassword.argtypes=[V,U,ctypes.c_char_p,U,ctypes.c_char_p,P(U),P(V),P(V)]
        self.sec.SecKeychainFindGenericPassword.restype=ctypes.c_int32
        self.sec.SecKeychainAddGenericPassword.argtypes=[V,U,ctypes.c_char_p,U,ctypes.c_char_p,U,V,P(V)]
        self.sec.SecKeychainAddGenericPassword.restype=ctypes.c_int32
        self.sec.SecKeychainItemModifyAttributesAndData.argtypes=[V,V,U,V]
        self.sec.SecKeychainItemModifyAttributesAndData.restype=ctypes.c_int32
        self.sec.SecKeychainItemDelete.argtypes=[V];self.sec.SecKeychainItemDelete.restype=ctypes.c_int32
        self.sec.SecKeychainItemFreeContent.argtypes=[V,V];self.cf.CFRelease.argtypes=[V]
    def _find(self):
        length=ctypes.c_uint32();data=ctypes.c_void_p();item=ctypes.c_void_p()
        code=self.sec.SecKeychainFindGenericPassword(None,len(self.service),self.service,len(self.account),self.account,ctypes.byref(length),ctypes.byref(data),ctypes.byref(item))
        if code==-25300:return '',None
        if code:raise CredentialError(f'macOS钥匙串无法读取（状态{code}），请解锁登录钥匙串并允许本地Python访问')
        try:return ctypes.string_at(data,length.value).decode(),item
        finally:self.sec.SecKeychainItemFreeContent(None,data)
    def load(self):
        value,item=self._find()
        if item:self.cf.CFRelease(item)
        return value
    def save(self,token):
        _,item=self._find();value=token.encode();buffer=ctypes.create_string_buffer(value)
        try:
            code=self.sec.SecKeychainItemModifyAttributesAndData(item,None,len(value),buffer) if item else self.sec.SecKeychainAddGenericPassword(None,len(self.service),self.service,len(self.account),self.account,len(value),buffer,None)
            if code:raise CredentialError(f'密钥未能保存到macOS钥匙串（状态{code}），请检查钥匙串权限')
        finally:
            ctypes.memset(buffer,0,len(value))
            if item:self.cf.CFRelease(item)
    def delete(self):
        _,item=self._find()
        if item:
            try:
                code=self.sec.SecKeychainItemDelete(item)
                if code:raise CredentialError(f'无法删除钥匙串项（状态{code}）')
            finally:self.cf.CFRelease(item)
