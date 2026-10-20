"""Run interactively on the authorized local terminal; never pass a secret on the command line."""
from getpass import getpass

import keyring


def main():
    backend = keyring.get_keyring()
    if not type(backend).__module__.startswith(("keyring.backends.Windows", "keyring.backends.macOS",
                                               "keyring.backends.SecretService")):
        raise SystemExit("需要受保护的系统凭据存储，已拒绝明文回退。")
    account = input("凭据名称 [model-api]: ").strip() or "model-api"
    secret = getpass("模型 API 密钥（不回显）: ")
    if not secret:
        raise SystemExit("未输入密钥，未作更改。")
    keyring.set_password("teacher-grading-assistant", account, secret)
    print("已写入系统凭据存储。")


if __name__ == "__main__":
    main()
