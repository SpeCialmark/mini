import secrets


def generate_token():
    token = secrets.token_hex(16)
    return token
