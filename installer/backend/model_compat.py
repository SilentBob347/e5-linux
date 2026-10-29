"""Explicit model exceptions, bound to one package/device/operation."""
import hashlib
import json
import secrets
import time

BOARDS = {'k1': 'ums9157_2h10', 'yuanhang41s': 'P720S11',
          'lym10k': 'RY5G', 'changxing60': 'P720S20'}


def android_warning(profile, model, board):
    expected_board = BOARDS.get(profile['profile'])
    if model in profile['android_models'] and (not expected_board or board == expected_board):
        return None
    return {'expected_profile': profile['profile'],
            'expected_models': profile['android_models'], 'expected_board': expected_board,
            'actual_model': model, 'actual_board': board}


def runtime_warning(expected, actual):
    if expected == actual:
        return None
    return {'expected_profile': expected, 'expected_models': [expected],
            'expected_board': None, 'actual_model': actual, 'actual_board': None}


def fingerprint(package, device, method):
    value = {'package': {k: package.get(k) for k in
                         ('adapter', 'profile', 'kernel', 'layout', 'payloads')},
             'device': {k: device.get(k) for k in
                        ('serial', 'cid', 'model', 'board', 'system', 'model_mismatch')},
             'method': method}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def same_token(value, expected):
    return isinstance(value, str) and secrets.compare_digest(value.encode(), expected.encode())


def decision(package, device, method, params):
    warning = device.get('model_mismatch')
    if package.get('adapter') != 'e5' or not warning:
        return None, None
    token = fingerprint(package, device, method)
    if (params.get('model_confirmation') == 'yes' and
            same_token(params.get('model_token'), token)):
        return None, {'fingerprint': token, 'confirmation': 'yes', 'confirmed_at': time.time()}
    return {'confirmation_required': 'model_mismatch', 'model_token': token,
            'warning': warning, 'serial_hint': device['serial'][-4:]}, None


def require_approval(record, actual):
    if record['package'].get('adapter') != 'e5' or not actual.get('model_mismatch'):
        return
    approval = record.get('model_override', {})
    wanted = fingerprint(record['package'], actual, record['choices']['method'])
    if (approval.get('confirmation') != 'yes' or
            not same_token(approval.get('fingerprint'), wanted)):
        raise ValueError('Model changed or confirmation is missing; review the plan again / '
                         '机型发生变化或尚未确认，请重新查看安装计划并输入 yes')
