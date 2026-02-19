#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Panel - 雲端硬碟管理面板
負責對外提供服務、管理節點、用戶、處理使用者請求
使用 SQLite 資料庫儲存資料
"""

import os
import json
import uuid
import hashlib
import time
import io
import requests
import sqlite3
from functools import wraps
from flask import Flask, request, jsonify, send_file, render_template_string, session, render_template
from werkzeug.utils import secure_filename

# 設定範本目錄
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size
app.config['SECRET_KEY'] = os.urandom(32)

# 確保資料目錄存在
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# 資料庫路徑
DB_PATH = os.path.join(DATA_DIR, 'data.db')

# 可用的權限列表
API_PERMISSIONS = {
    # 檔案相關權限
    'file:read': '讀取檔案列表',
    'file:upload': '上傳檔案',
    'file:download': '下載檔案',
    'file:delete': '刪除檔案',
    'file:move': '移動檔案',
    'file:preview': '預覽檔案',
    
    # 資料夾相關權限
    'folder:read': '讀取資料夾列表',
    'folder:list': '列出資料夾內容',
    'folder:create': '建立資料夾',
    'folder:delete': '刪除資料夾',
    'folder:write': '移動資料夾',
    
    # 用戶相關權限
    'user:read': '讀取用戶資訊',
    'user:create': '建立用戶',
    'user:update': '更新用戶',
    'user:delete': '刪除用戶',
    'user:quota': '設定用戶配額',
    
    # 節點相關權限
    'node:read': '讀取節點資訊',
    'node:create': '建立節點',
    'node:update': '更新節點',
    'node:delete': '刪除節點',
    'node:config': '產生節點配置',
    # 認證相關權限
    'auth:login': '登入驗證',
    'auth:check': '檢查登入狀態',
}

# ==================== 資料庫管理 ====================

def get_db():
    """取得資料庫連線"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """初始化資料庫"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 用戶表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at REAL NOT NULL
        )
    ''')
    
    # 用戶配額表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quotas (
            user_id TEXT PRIMARY KEY,
            quota INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            allowed_nodes TEXT DEFAULT '[]',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # 節點綁定表 - 存储token_id和token的綁定關係
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS node_bindings (
            token_id TEXT PRIMARY KEY,
            token TEXT NOT NULL,
            node_id TEXT,
            node_name TEXT,
            status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL,
            bound_at REAL
        )
    ''')
    
    # 節點表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            name TEXT,
            token TEXT,
            token_id TEXT,
            host TEXT,
            port INTEGER,
            connection_url TEXT,
            registered_at REAL,
            last_heartbeat REAL,
            status TEXT DEFAULT 'offline',
            capacity INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            redundancy INTEGER DEFAULT 0,
            storage_limit INTEGER DEFAULT 0,
            max_file_size INTEGER DEFAULT 104857600
        )
    ''')
    
    # 檔案表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            size INTEGER DEFAULT 0,
            node_id TEXT,
            node_name TEXT,
            user_id TEXT,
            uploaded_at REAL,
            checksum TEXT,
            path TEXT DEFAULT '',
            folder TEXT DEFAULT '',
            FOREIGN KEY (node_id) REFERENCES nodes(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # 如果 folder 欄位不存在，則新增
    try:
        cursor.execute('SELECT folder FROM files LIMIT 1')
    except:
        cursor.execute('ALTER TABLE files ADD COLUMN folder TEXT DEFAULT ""')
    
    # 撤銷的 Tokens 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS revoked_tokens (
            token TEXT PRIMARY KEY,
            revoked_at REAL NOT NULL
        )
    ''')
    
    # API Tokens 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_tokens (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            permissions TEXT DEFAULT '[]',
            enabled INTEGER DEFAULT 1,
            created_at REAL NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"資料庫初始化完成: {DB_PATH}")

# ==================== 用戶資料操作 ====================

def load_users():
    """從資料庫載入用戶"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users')
    users = {}
    for row in cursor.fetchall():
        users[row['id']] = dict(row)
    conn.close()
    return users

def save_users(users):
    """儲存用戶到資料庫"""
    conn = get_db()
    cursor = conn.cursor()
    for user_id, user in users.items():
        cursor.execute('''
            INSERT OR REPLACE INTO users (id, username, password, role, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, user.get('username'), user.get('password'), user.get('role'), user.get('created_at')))
    conn.commit()
    conn.close()

def load_quotas():
    """從資料庫載入配額"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM quotas')
    quotas = {}
    for row in cursor.fetchall():
        quotas[row['user_id']] = {
            'quota': row['quota'],
            'used': row['used'],
            'allowed_nodes': json.loads(row['allowed_nodes']) if row['allowed_nodes'] else []
        }
    conn.close()
    return quotas

def save_quotas(quotas):
    """儲存配額到資料庫"""
    conn = get_db()
    cursor = conn.cursor()
    for user_id, quota in quotas.items():
        cursor.execute('''
            INSERT OR REPLACE INTO quotas (user_id, quota, used, allowed_nodes)
            VALUES (?, ?, ?, ?)
        ''', (user_id, quota.get('quota', 0), quota.get('used', 0), json.dumps(quota.get('allowed_nodes', []))))
    conn.commit()
    conn.close()

# ==================== 節點綁定操作 ====================

def load_bindings():
    """從資料庫載入節點綁定"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM node_bindings')
    bindings = {}
    for row in cursor.fetchall():
        bindings[row['token_id']] = dict(row)
    conn.close()
    return bindings

def save_binding(token_id, token, node_name):
    """儲存節點綁定"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO node_bindings (token_id, token, status, created_at)
        VALUES (?, ?, 'pending', ?)
    ''', (token_id, token, time.time()))
    conn.commit()
    conn.close()

def get_binding_by_token_id(token_id):
    """通過token_id獲取綁定"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM node_bindings WHERE token_id = ?', (token_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def verify_binding(token_id, token):
    """驗證綁定是否正確"""
    binding = get_binding_by_token_id(token_id)
    if not binding:
        return False, 'Token ID 不存在'
    if binding.get('token') != token:
        return False, 'Token 驗證失敗'
    if binding.get('status') == 'rejected':
        return False, '此節點已被移除，請聯絡管理員重新設定'
    return True, '驗證成功'

def update_binding_status(token_id, node_id, node_name, status='bound'):
    """更新綁定狀態"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE node_bindings 
        SET status = ?, node_id = ?, node_name = ?, bound_at = ?
        WHERE token_id = ?
    ''', (status, node_id, node_name, time.time() if status == 'bound' else None, token_id))
    conn.commit()
    conn.close()

def remove_binding(token_id):
    """刪除節點綁定"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM node_bindings WHERE token_id = ?', (token_id,))
    conn.commit()
    conn.close()

# ==================== 節點資料操作 ====================

def load_nodes():
    """從資料庫載入節點"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM nodes')
    nodes = {}
    for row in cursor.fetchall():
        nodes[row['id']] = dict(row)
    conn.close()
    return nodes

def save_nodes(nodes):
    """儲存節點到資料庫"""
    conn = get_db()
    cursor = conn.cursor()
    for node_id, node in nodes.items():
        cursor.execute('''
            INSERT OR REPLACE INTO nodes 
            (id, name, token, token_id, host, port, connection_url, registered_at, last_heartbeat, status, capacity, used, redundancy, storage_limit, max_file_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            node_id, node.get('name'), node.get('token'), node.get('token_id'),
            node.get('host'), node.get('port'), node.get('connection_url'),
            node.get('registered_at'), node.get('last_heartbeat'), node.get('status'),
            node.get('capacity', 0), node.get('used', 0), node.get('redundancy', 0),
            node.get('storage_limit', 0), node.get('max_file_size', 104857600)
        ))
    conn.commit()
    conn.close()

def get_node_by_token_id(token_id):
    """通過token_id獲取節點"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM nodes WHERE token_id = ?', (token_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# ==================== 檔案資料操作 ====================

def load_files():
    """從資料庫載入檔案"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM files')
    files = {}
    for row in cursor.fetchall():
        files[row['id']] = dict(row)
    conn.close()
    return files

def save_files(files):
    """儲存檔案到資料庫"""
    conn = get_db()
    cursor = conn.cursor()
    for file_id, file_info in files.items():
        cursor.execute('''
            INSERT OR REPLACE INTO files 
            (id, name, size, node_id, node_name, user_id, uploaded_at, checksum, path, folder)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            file_id, file_info.get('name'), file_info.get('size', 0),
            file_info.get('node_id'), file_info.get('node_name'),
            file_info.get('user_id'), file_info.get('uploaded_at'),
            file_info.get('checksum', ''), file_info.get('path', ''), file_info.get('folder', '')
        ))
        conn.commit()
    conn.close()

# ==================== API Token 操作 ====================

def load_api_tokens():
    """從資料庫載入 API Tokens"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM api_tokens')
    tokens = {}
    for row in cursor.fetchall():
        tokens[row['id']] = {
            'id': row['id'],
            'name': row['name'],
            'token': row['token'],
            'permissions': json.loads(row['permissions']) if row['permissions'] else [],
            'enabled': bool(row['enabled']),
            'created_at': row['created_at']
        }
    conn.close()
    return tokens

def save_api_tokens(tokens):
    """儲存 API Tokens 到資料庫"""
    conn = get_db()
    cursor = conn.cursor()
    for token_id, token_info in tokens.items():
        cursor.execute('''
            INSERT OR REPLACE INTO api_tokens (id, name, token, permissions, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            token_id, token_info.get('name'), token_info.get('token'),
            json.dumps(token_info.get('permissions', [])), 
            1 if token_info.get('enabled', True) else 0,
            token_info.get('created_at')
        ))
    conn.commit()
    conn.close()

def is_token_revoked(token):
    """檢查 Token 是否已被撤銷"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM revoked_tokens WHERE token = ?', (token,))
    result = cursor.fetchone()[0] > 0
    conn.close()
    return result

def revoke_token(token):
    """撤銷 Token"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO revoked_tokens (token, revoked_at) VALUES (?, ?)', (token, time.time()))
    conn.commit()
    conn.close()

# ==================== 工具函數 ====================

def generate_token():
    random_str = str(uuid.uuid4()) + str(time.time())
    return hashlib.sha256(random_str.encode()).hexdigest()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_api_token_permissions(token):
    """獲取 API Token 的權限"""
    tokens = load_api_tokens()
    for token_id, token_info in tokens.items():
        if token_info.get('token') == token:
            return token_info.get('permissions', [])
    return []

def is_api_token_valid(token):
    """檢查 API Token 是否有效"""
    tokens = load_api_tokens()
    for token_id, token_info in tokens.items():
        if token_info.get('token') == token:
            return token_info.get('enabled', True)
    return False

# API Token 驗證裝飾器
def api_token_required(permission=None):
    """API Token 驗證裝飾器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id')
            if user_id:
                return f(*args, **kwargs)
            
            api_token = request.headers.get('X-API-Token')
            if not api_token:
                return jsonify({'success': False, 'error': '需要 API Token'}), 401
            
            if not is_api_token_valid(api_token):
                return jsonify({'success': False, 'error': '無效的 API Token'}), 401
            
            if permission:
                permissions = get_api_token_permissions(api_token)
                if permission not in permissions:
                    return jsonify({'success': False, 'error': '權限不足'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# 認證裝飾器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': '請先登入'}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': '請先登入'}), 401
        users = load_users()
        user = users.get(user_id, {})
        if user.get('role') != 'admin':
            return jsonify({'success': False, 'error': '權限不足'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ==================== 認證 API ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '')
    password = data.get('password', '')
    
    users = load_users()
    for user_id, user in users.items():
        if user.get('username') == username:
            if user.get('password') == hash_password(password):
                session['user_id'] = user_id
                session['username'] = username
                session['role'] = user.get('role')
                return jsonify({'success': True, 'user': {'id': user_id, 'username': username, 'role': user.get('role')}})
            return jsonify({'success': False, 'error': '密碼錯誤'}), 401
    return jsonify({'success': False, 'error': '帳號不存在'}), 404

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    user_id = session.get('user_id')
    if user_id:
        quotas = load_quotas()
        user_quota = quotas.get(user_id, {})
        return jsonify({
            'success': True, 
            'logged_in': True, 
            'user': {
                'id': user_id, 
                'username': session.get('username'), 
                'role': session.get('role'),
                'storage_quota': user_quota.get('quota', 0),
                'storage_used': user_quota.get('used', 0)
            }
        })
    return jsonify({'success': True, 'logged_in': False})

# ==================== 用戶管理 API ====================

@app.route('/api/user/list', methods=['GET'])
@api_token_required('user:read')
@admin_required
def list_users():
    users = load_users()
    quotas = load_quotas()
    user_list = []
    for user_id, user in users.items():
        quota = quotas.get(user_id, {})
        user_list.append({
            'id': user_id, 
            'username': user.get('username'), 
            'role': user.get('role'), 
            'created_at': user.get('created_at'), 
            'storage_quota': quota.get('quota', 0), 
            'storage_used': quota.get('used', 0)
        })
    return jsonify({'success': True, 'users': user_list})

@app.route('/api/user/create', methods=['POST'])
@admin_required
def create_user():
    data = request.get_json()
    username = data.get('username', '')
    password = data.get('password', '')
    role = data.get('role', 'user')
    
    users = load_users()
    for user in users.values():
        if user.get('username') == username:
            return jsonify({'success': False, 'error': '帳號已存在'}), 400
    
    user_id = str(uuid.uuid4())
    users[user_id] = {'id': user_id, 'username': username, 'password': hash_password(password), 'role': role, 'created_at': time.time()}
    save_users(users)
    
    quotas = load_quotas()
    quotas[user_id] = {'quota': 0, 'used': 0, 'nodes': [], 'allowed_nodes': []}
    save_quotas(quotas)
    return jsonify({'success': True, 'user_id': user_id})

@app.route('/api/user/<user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    users = load_users()
    if user_id not in users:
        return jsonify({'success': False, 'error': '用戶不存在'}), 404
    if user_id == session.get('user_id'):
        return jsonify({'success': False, 'error': '不能刪除自己'}), 400
    del users[user_id]
    save_users(users)
    quotas = load_quotas()
    if user_id in quotas:
        del quotas[user_id]
        save_quotas(quotas)
    return jsonify({'success': True})

@app.route('/api/user/quota', methods=['POST'])
@admin_required
def set_user_quota():
    data = request.get_json()
    user_id = data.get('user_id')
    quota = data.get('quota', 0)
    node_ids = data.get('nodes', [])
    quotas = load_quotas()
    quotas[user_id] = {'quota': int(quota), 'used': quotas.get(user_id, {}).get('used', 0), 'nodes': node_ids}
    save_quotas(quotas)
    return jsonify({'success': True})

@app.route('/api/user/<user_id>', methods=['GET'])
@admin_required
def get_user(user_id):
    users = load_users()
    quotas = load_quotas()
    if user_id not in users:
        return jsonify({'success': False, 'error': '用戶不存在'}), 404
    user = users[user_id]
    quota = quotas.get(user_id, {})
    return jsonify({
        'success': True,
        'user': {
            'id': user_id,
            'username': user.get('username'),
            'role': user.get('role'),
            'created_at': user.get('created_at'),
            'storage_quota': quota.get('quota', 0),
            'storage_used': quota.get('used', 0),
            'allowed_nodes': quota.get('allowed_nodes', [])
        }
    })

@app.route('/api/user/<user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    users = load_users()
    quotas = load_quotas()
    if user_id not in users:
        return jsonify({'success': False, 'error': '用戶不存在'}), 404
    
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    role = data.get('role')
    quota = data.get('storage_quota', 0)
    allowed_nodes = data.get('allowed_nodes', [])
    
    if username:
        for uid, u in users.items():
            if uid != user_id and u.get('username') == username:
                return jsonify({'success': False, 'error': '帳號已存在'}), 400
        users[user_id]['username'] = username
    
    if password:
        users[user_id]['password'] = hash_password(password)
    
    if role:
        users[user_id]['role'] = role
    
    save_users(users)
    
    if user_id not in quotas:
        quotas[user_id] = {'quota': 0, 'used': 0, 'nodes': [], 'allowed_nodes': []}
    quotas[user_id]['quota'] = int(quota)
    quotas[user_id]['allowed_nodes'] = allowed_nodes
    save_quotas(quotas)
    
    return jsonify({'success': True})

# ==================== SSE ====================

@app.route('/api/node/stream')
def node_stream():
    from flask import Response
    def generate():
        while True:
            nodes = load_nodes()
            current_time = time.time()
            for node_id, node_info in nodes.items():
                node_info['status'] = 'online' if current_time - node_info.get('last_heartbeat', 0) <= 90 else 'offline'
            yield f"data: {json.dumps({'nodes': nodes, 'timestamp': current_time})}\n\n"
            time.sleep(3)
    return Response(generate(), mimetype='text/event-stream')

# ==================== Node 綁定 API ====================

@app.route('/api/node/verify', methods=['POST'])
def verify_node():
    """驗證節點 token_id 是否正確（第一步）"""
    data = request.get_json()
    token_id = data.get('token_id', '')
    
    if not token_id:
        return jsonify({'success': False, 'error': '缺少 token_id'}), 400
    
    binding = get_binding_by_token_id(token_id)
    if not binding:
        return jsonify({'success': False, 'error': 'Token ID 不存在，請聯絡管理員取得正確配置'}), 404
    
    if binding.get('status') == 'rejected':
        return jsonify({'success': False, 'error': '此節點已被移除，請聯絡管理員重新設定'}), 403
    
    return jsonify({
        'success': True,
        'message': 'Token ID 驗證成功，請繼續發送 Token 進行綁定'
    })

@app.route('/api/node/bind', methods=['POST'])
def bind_node():
    """綁定節點（第二步）"""
    data = request.get_json()
    token_id = data.get('token_id', '')
    token = data.get('token', '')
    node_uuid = data.get('uuid', '')
    node_name = data.get('name', 'Unnamed Node')
    node_host = data.get('host', request.host)
    node_port = data.get('port', 5001)
    node_capacity = data.get('capacity', 0)
    
    if not token_id or not token:
        return jsonify({'success': False, 'error': '缺少必要參數'}), 400
    
    # 驗證 token
    valid, message = verify_binding(token_id, token)
    if not valid:
        return jsonify({'success': False, 'error': message}), 403
    
    # 檢查節點是否已綁定
    existing_node = get_node_by_token_id(token_id)
    if existing_node:
        # 更新現有節點
        existing_node.update({
            'name': node_name,
            'host': node_host,
            'port': node_port,
            'last_heartbeat': time.time(),
            'status': 'online',
            'capacity': node_capacity
        })
        nodes = load_nodes()
        nodes[existing_node['id']] = existing_node
        save_nodes(nodes)
        
        update_binding_status(token_id, existing_node['id'], node_name, 'bound')
        
        return jsonify({
            'success': True,
            'message': '節點已綁定',
            'node_id': existing_node['id']
        })
    
    # 建立新節點
    node_id = node_uuid if node_uuid else str(uuid.uuid4())
    nodes = load_nodes()
    nodes[node_id] = {
        'id': node_id,
        'name': node_name,
        'token': token,
        'token_id': token_id,
        'host': node_host,
        'port': node_port,
        'registered_at': time.time(),
        'last_heartbeat': time.time(),
        'status': 'online',
        'capacity': node_capacity,
        'used': 0
    }
    save_nodes(nodes)
    
    # 更新綁定狀態
    update_binding_status(token_id, node_id, node_name, 'bound')
    
    return jsonify({
        'success': True,
        'message': '節點綁定成功',
        'node_id': node_id
    })

@app.route('/api/node/heartbeat', methods=['POST'])
def node_heartbeat():
    """節點心跳"""
    data = request.get_json()
    token_id = data.get('token_id', '')
    token = data.get('token', '')
    
    # 驗證 token
    valid, message = verify_binding(token_id, token)
    if not valid:
        return jsonify({'success': False, 'error': message}), 403
    
    # 找到節點
    node = get_node_by_token_id(token_id)
    if not node:
        return jsonify({'success': False, 'error': '節點未找到'}), 404
    
    nodes = load_nodes()
    if node['id'] in nodes:
        node_capacity = nodes[node['id']].get('storage_limit', 0)
        if node_capacity == 0:
            node_capacity = data.get('capacity', nodes[node['id']].get('capacity', 0))
        nodes[node['id']].update({
            'last_heartbeat': time.time(),
            'status': 'online',
            'capacity': node_capacity,
            'used': data.get('used', 0)
        })
        save_nodes(nodes)
    
    return jsonify({'success': True})

@app.route('/api/node/list', methods=['GET'])
@api_token_required('node:read')
@login_required
def list_nodes():
    user_id = session.get('user_id')
    role = session.get('role')
    quotas = load_quotas()
    user_quota = quotas.get(user_id, {})
    allowed_nodes = user_quota.get('allowed_nodes', [])
    
    nodes = load_nodes()
    current_time = time.time()
    
    for node_id, node_info in nodes.items():
        node_info['status'] = 'offline' if current_time - node_info.get('last_heartbeat', 0) > 90 else 'online'
    
    if role != 'admin' and allowed_nodes:
        nodes = {k: v for k, v in nodes.items() if k in allowed_nodes}
    
    return jsonify({'success': True, 'nodes': nodes})

@app.route('/api/node/<node_id>', methods=['DELETE'])
@admin_required
def delete_node(node_id):
    nodes = load_nodes()
    if node_id in nodes:
        node = nodes[node_id]
        token_id = node.get('token_id')
        
        # 刪除節點
        del nodes[node_id]
        save_nodes(nodes)
        
        # 刪除綁定（這樣節點下次連線會被拒絕）
        if token_id:
            remove_binding(token_id)
        
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '節點不存在'}), 404

@app.route('/api/node/config', methods=['POST'])
@admin_required
def create_node_config():
    """建立節點配置"""
    data = request.get_json()
    
    # 生成 token_id 和 token
    token_id = str(uuid.uuid4())
    token = generate_token()
    
    # 儲存綁定關係
    node_name = data.get('name', 'Unnamed Node')
    save_binding(token_id, token, node_name)
    
    connection_url = data.get('connection_url', '')
    host = '0.0.0.0'
    port = 443
    
    if ':' in connection_url and not connection_url.startswith('http'):
        parts = connection_url.rsplit(':', 1)
        if len(parts) == 2 and parts[1].isdigit():
            host = parts[0]
            port = int(parts[1])
    elif connection_url.startswith('http://'):
        url_without_protocol = connection_url.replace('http://', '')
        if ':' in url_without_protocol:
            parts = url_without_protocol.rsplit(':', 1)
            if len(parts) == 2 and parts[1].isdigit():
                host = parts[0]
                port = int(parts[1])
    elif connection_url.startswith('https://'):
        url_without_protocol = connection_url.replace('https://', '')
        if ':' in url_without_protocol:
            parts = url_without_protocol.rsplit(':', 1)
            if len(parts) == 2 and parts[1].isdigit():
                host = parts[0]
                port = int(parts[1])
    
    storage_limit = data.get('storage_limit', 0)
    redundancy = data.get('redundancy', 0)
    max_file_size = data.get('max_file_size', 100 * 1024 * 1024)
    heartbeat_interval = data.get('heartbeat_interval', 30)
    panel_url = data.get('panel_url', 'http://localhost:5000')
    
    # 建立節點記錄（立即顯示在後台，狀態為離線）
    node_id = str(uuid.uuid4())
    nodes = load_nodes()
    nodes[node_id] = {
        'id': node_id,
        'name': node_name,
        'token': token,
        'token_id': token_id,
        'host': host,
        'port': port,
        'connection_url': connection_url,
        'registered_at': time.time(),
        'last_heartbeat': 0,  # 設為 0 表示從未收到心跳
        'status': 'offline',  # 立即顯示為離線
        'capacity': storage_limit,
        'used': 0,
        'redundancy': redundancy,
        'storage_limit': storage_limit,
        'max_file_size': max_file_size
    }
    save_nodes(nodes)
    
    config_content = f"""# HimCloud Node 配置檔案
# uuid 將在節點首次連線後自動填充
uuid: "{node_id}"
token_id: "{token_id}"
token: "{token}"

node:
  name: "{node_name}"
  host: "{host}"
  port: {port}
  max_file_size: {max_file_size}
  max_storage_size: {storage_limit}
  data: "storage"

heartbeat_interval: {heartbeat_interval}
panel_url: "{panel_url}"
"""
    
    return jsonify({
        'success': True,
        'token_id': token_id,
        'token': token,
        'node_id': node_id,
        'config_content': config_content
    })

@app.route('/api/token/generate', methods=['POST'])
@admin_required
def generate_node_token():
    return jsonify({'success': True, 'token': generate_token()})

# ==================== 開發者 API Token 管理 ====================

@app.route('/api/dev/token/list', methods=['GET'])
@admin_required
def list_api_tokens():
    tokens = load_api_tokens()
    return jsonify({'success': True, 'tokens': tokens})

@app.route('/api/dev/token/create', methods=['POST'])
@admin_required
def create_api_token():
    data = request.get_json() or {}
    name = data.get('name', 'API Token')
    permissions = data.get('permissions', [])
    enabled = data.get('enabled', True)
    
    valid_permissions = list(API_PERMISSIONS.keys())
    for perm in permissions:
        if perm not in valid_permissions:
            return jsonify({'success': False, 'error': f'無效的權限: {perm}'}), 400
    
    token = generate_token()
    token_id = str(uuid.uuid4())
    
    tokens = load_api_tokens()
    tokens[token_id] = {
        'id': token_id,
        'name': name,
        'token': token,
        'permissions': permissions,
        'enabled': enabled,
        'created_at': time.time()
    }
    save_api_tokens(tokens)
    
    return jsonify({
        'success': True,
        'token_id': token_id,
        'token': token,
        'name': name,
        'permissions': permissions,
        'enabled': enabled
    })

@app.route('/api/dev/token/<token_id>', methods=['PUT'])
@admin_required
def update_api_token(token_id):
    tokens = load_api_tokens()
    if token_id not in tokens:
        return jsonify({'success': False, 'error': 'Token 不存在'}), 404
    
    data = request.get_json() or {}
    
    if 'name' in data:
        tokens[token_id]['name'] = data['name']
    if 'permissions' in data:
        valid_permissions = list(API_PERMISSIONS.keys())
        for perm in data['permissions']:
            if perm not in valid_permissions:
                return jsonify({'success': False, 'error': f'無效的權限: {perm}'}), 400
        tokens[token_id]['permissions'] = data['permissions']
    if 'enabled' in data:
        tokens[token_id]['enabled'] = data['enabled']
    
    save_api_tokens(tokens)
    return jsonify({'success': True})

@app.route('/api/dev/token/<token_id>', methods=['DELETE'])
@admin_required
def delete_api_token(token_id):
    tokens = load_api_tokens()
    if token_id not in tokens:
        return jsonify({'success': False, 'error': 'Token 不存在'}), 404
    
    del tokens[token_id]
    save_api_tokens(tokens)
    return jsonify({'success': True})

@app.route('/api/dev/token/<token_id>/regenerate', methods=['POST'])
@admin_required
def regenerate_api_token(token_id):
    tokens = load_api_tokens()
    if token_id not in tokens:
        return jsonify({'success': False, 'error': 'Token 不存在'}), 404
    
    new_token = generate_token()
    tokens[token_id]['token'] = new_token
    tokens[token_id]['created_at'] = time.time()
    save_api_tokens(tokens)
    
    return jsonify({
        'success': True,
        'token': new_token
    })

@app.route('/api/dev/permissions', methods=['GET'])
def get_available_permissions():
    return jsonify({'success': True, 'permissions': API_PERMISSIONS})

# ==================== 檔案管理 API ====================

@app.route('/api/file/upload', methods=['POST'])
@api_token_required('file:upload')
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '無檔案'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': '檔案名稱為空'}), 400
    
    user_id = session.get('user_id')
    role = session.get('role')
    quotas = load_quotas()
    user_quota = quotas.get(user_id, {})
    allowed_nodes = user_quota.get('allowed_nodes', [])
    
    target_node_id = request.form.get('node_id')
    all_nodes = load_nodes()
    
    if role != 'admin' and allowed_nodes:
        nodes = {k: v for k, v in all_nodes.items() if k in allowed_nodes}
    else:
        nodes = all_nodes
    
    if target_node_id and target_node_id in nodes:
        node = nodes[target_node_id]
    else:
        online_nodes = [n for n in nodes.values() if n.get('status') == 'online']
        if not online_nodes:
            return jsonify({'success': False, 'error': '無可用節點'}), 500
        node = online_nodes[0]
    
    file_content = file.read()
    file_size = len(file_content)
    
    if user_quota.get('quota', 0) > 0:
        if user_quota.get('used', 0) + file_size > user_quota.get('quota', 0):
            return jsonify({'success': False, 'error': '儲存空間不足'}), 400
    
    files = load_files()
    file_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    
    try:
        response = requests.post(
            f"http://{node['host']}:{node['port']}/api/node/store", 
            files={'file': (filename, file_content)}, 
            data={'file_id': file_id, 'user_id': user_id, 'folder': ''}, 
            timeout=30,
            cookies=request.cookies
        )
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                files[file_id] = {
                    'id': file_id, 
                    'name': filename, 
                    'size': file_size, 
                    'node_id': node['id'], 
                    'node_name': node['name'], 
                    'user_id': user_id, 
                    'uploaded_at': time.time(), 
                    'checksum': result.get('checksum', '')
                }
                save_files(files)
                quotas[user_id]['used'] = quotas[user_id].get('used', 0) + file_size
                save_quotas(quotas)
                return jsonify({'success': True, 'file_id': file_id, 'node': node['name']})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': False, 'error': '上傳失敗'}), 500

# ==================== 檔案移動 API (必須在動態路由之前) ====================

@app.route('/api/file/move', methods=['POST'])
@api_token_required('file:move')
@login_required
def move_file():
    user_id = session.get('user_id')
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '無請求數據'}), 400
    except Exception:
        return jsonify({'success': False, 'error': '無效的請求'}), 400
    
    file_id = data.get('file_id')
    target_folder = data.get('target_folder', '').strip() if data.get('target_folder') else ''
    node_id = data.get('node_id')
    
    if not file_id:
        return jsonify({'success': False, 'error': '無檔案ID'}), 400
    
    if not node_id:
        return jsonify({'success': False, 'error': '無節點ID'}), 400
    
    nodes = load_nodes()
    if node_id not in nodes:
        return jsonify({'success': False, 'error': '節點不存在'}), 404
    
    node = nodes[node_id]
    
    try:
        response = requests.post(
            f"http://{node['host']}:{node['port']}/api/node/file/move",
            json={'user_id': user_id, 'file_id': file_id, 'target_folder': target_folder},
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )
        
        try:
            result = response.json()
            return jsonify(result), response.status_code
        except Exception:
            return jsonify({'success': False, 'error': f'節點返回無效回應: {response.status_code}'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ====================

@app.route('/api/file/list', methods=['GET'])
@api_token_required('file:read')
@login_required
def list_files():
    user_id = session.get('user_id')
    role = session.get('role')
    files = load_files()
    if role == 'admin':
        return jsonify({'success': True, 'files': files})
    return jsonify({'success': True, 'files': {k: v for k, v in files.items() if v.get('user_id') == user_id}})

@app.route('/api/file/by-node/<node_id>', methods=['GET'])
@login_required
def list_files_by_node(node_id):
    user_id = session.get('user_id')
    role = session.get('role')
    files = load_files()
    node_files = {k: v for k, v in files.items() if v.get('node_id') == node_id}
    if role != 'admin':
        node_files = {k: v for k, v in node_files.items() if v.get('user_id') == user_id}
    return jsonify({'success': True, 'files': node_files})

@app.route('/api/file/download/<file_id>', methods=['GET'])
@api_token_required('file:download')
@login_required
def download_file(file_id):
    from flask import Response
    
    user_id = session.get('user_id')
    role = session.get('role')
    stream = request.args.get('stream', 'false').lower() == 'true'
    
    # 檢查是否為從 Node 直接下載（後台管理使用）
    node_id = request.args.get('node_id')
    from_node = request.args.get('from_node', 'false').lower() == 'true'
    
    if from_node and node_id:
        # 從 Node 直接下載（後台管理使用）
        nodes = load_nodes()
        if node_id not in nodes:
            return jsonify({'success': False, 'error': '節點不存在'}), 404
        
        node = nodes[node_id]
        
        # 獲取 Node 的認證資訊
        node_token = node.get('token', '')
        node_token_id = node.get('token_id', '')
        
        # 直接從 Node 下載
        try:
            # 使用 query string 傳遞 token（更可靠的認證方式）
            params = {
                'token': node_token
            }
            
            if stream:
                response = requests.get(
                    f"http://{node['host']}:{node['port']}/api/node/retrieve/{file_id}?stream=true", 
                    timeout=30, 
                    stream=True,
                    params=params
                )
                if response.status_code == 200:
                    content_type = response.headers.get('Content-Type', 'application/octet-stream')
                    
                    def generate():
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                yield chunk
                    
                    return Response(generate(), mimetype=content_type)
            else:
                response = requests.get(
                    f"http://{node['host']}:{node['port']}/api/node/retrieve/{file_id}", 
                    timeout=30, 
                    stream=True,
                    params=params
                )
                if response.status_code == 200:
                    # 嘗試獲取檔案名稱
                    content_disposition = response.headers.get('Content-Disposition', '')
                    filename = None
                    if 'filename=' in content_disposition:
                        import re
                        match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)', content_disposition)
                        if match:
                            filename = match.group(1).strip('"\'')
                    
                    return send_file(response.raw, download_name=filename, as_attachment=True)
                elif response.status_code == 404:
                    return jsonify({'success': False, 'error': '檔案在節點上不存在'}), 404
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
        return jsonify({'success': False, 'error': '下載失敗'}), 500
    
    # 原本的邏輯：從 Panel 資料庫查找
    files = load_files()
    
    if file_id not in files:
        return jsonify({'success': False, 'error': '檔案不存在'}), 404
    
    file_info = files[file_id]
    if role != 'admin' and file_info.get('user_id') != user_id:
        return jsonify({'success': False, 'error': '無權存取'}), 403
    
    nodes = load_nodes()
    node = nodes.get(file_info['node_id'])
    if not node:
        return jsonify({'success': False, 'error': '節點不存在'}), 404
    
    # 獲取 Node 的認證資訊
    node_token = node.get('token', '')
    node_token_id = node.get('token_id', '')
    
    try:
        headers = {
            'X-Token-Id': node_token_id,
            'token': node_token
        }
        
        if stream:
            response = requests.get(
                f"http://{node['host']}:{node['port']}/api/node/retrieve/{file_id}?stream=true", 
                timeout=30, 
                stream=True,
                headers=headers
            )
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', 'application/octet-stream')
                
                def generate():
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk
                
                return Response(generate(), mimetype=content_type)
        else:
            response = requests.get(
                f"http://{node['host']}:{node['port']}/api/node/retrieve/{file_id}", 
                timeout=30, 
                stream=True,
                headers=headers
            )
            if response.status_code == 200:
                return send_file(response.raw, download_name=file_info['name'], as_attachment=True)
            elif response.status_code == 404:
                return jsonify({'success': False, 'error': '檔案在節點上不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': False, 'error': '下載失敗'}), 500

@app.route('/api/file/<file_id>', methods=['DELETE'])
@api_token_required('file:delete')
@login_required
def delete_file(file_id):
    files = load_files()
    user_id = session.get('user_id')
    role = session.get('role')
    
    if file_id not in files:
        return jsonify({'success': False, 'error': '檔案不存在'}), 404
    
    file_info = files[file_id]
    if role != 'admin' and file_info.get('user_id') != user_id:
        return jsonify({'success': False, 'error': '無權存取'}), 403
    
    node_id = file_info['node_id']
    file_size = file_info.get('size', 0)
    nodes = load_nodes()
    
    # 先嘗試從 Node 刪除，但無論成功失敗都從 Panel 資料庫刪除
    if node_id in nodes:
        node = nodes[node_id]
        try:
            response = requests.delete(f"http://{node['host']}:{node['port']}/api/node/delete/{file_id}", timeout=10)
            # 即使 Node 返回 404（檔案不存在），也繼續從 Panel 資料庫刪除
        except Exception:
            # 連線失敗也繼續，因為可能是 Node 已離線或檔案已刪除
            pass
    
    # 從 Panel 資料庫刪除
    del files[file_id]
    save_files(files)
    
    # 更新配額
    quotas = load_quotas()
    file_user_id = file_info.get('user_id')
    if file_user_id in quotas:
        quotas[file_user_id]['used'] = max(0, quotas[file_user_id].get('used', 0) - file_size)
        save_quotas(quotas)
    return jsonify({'success': True, 'message': '檔案已刪除'})

# ==================== 批次下載 API ====================

@app.route('/api/file/batch-download', methods=['POST'])
@api_token_required('file:download')
@login_required
def batch_download_files():
    """批次下載多個檔案為 ZIP 壓縮檔"""
    user_id = session.get('user_id')
    role = session.get('role')
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '無請求數據'}), 400
    except Exception:
        return jsonify({'success': False, 'error': '無效的請求'}), 400
    
    file_ids = data.get('file_ids', [])
    node_id = data.get('node_id')
    
    if not file_ids:
        return jsonify({'success': False, 'error': '請選擇要下載的檔案'}), 400
    
    if not node_id:
        return jsonify({'success': False, 'error': '請指定節點ID'}), 400
    
    nodes = load_nodes()
    if node_id not in nodes:
        return jsonify({'success': False, 'error': '節點不存在'}), 404
    
    node = nodes[node_id]
    
    # 獲取 Node 的認證資訊
    node_token = node.get('token', '')
    node_token_id = node.get('token_id', '')
    
    try:
        # 調用 Node 的批次下載 API
        response = requests.post(
            f"http://{node['host']}:{node['port']}/api/node/batch-download",
            json={'file_ids': file_ids, 'user_id': user_id},
            timeout=300,  # 較長的超時時間因為要生成 ZIP
            headers={
                'X-Token-Id': node_token_id,
                'token': node_token,
                'Content-Type': 'application/json'
            },
            stream=True
        )
        
        if response.status_code == 200:
            # 直接將 Node 的回應轉發給客戶端
            from flask import Response
            return Response(
                response.iter_content(chunk_size=8192),
                mimetype='application/zip',
                headers={
                    'Content-Disposition': f'attachment; filename=download_{int(time.time())}.zip'
                }
            )
        else:
            try:
                error_data = response.json()
                return jsonify(error_data), response.status_code
            except:
                return jsonify({'success': False, 'error': f'下載失敗: {response.status_code}'}), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== Node 檔案列表 API ====================

@app.route('/api/node/files', methods=['GET'])
@login_required
def list_node_files():
    """從 Node 獲取檔案列表"""
    user_id = session.get('user_id')
    role = session.get('role')
    node_id = request.args.get('node_id')
    
    if not node_id:
        return jsonify({'success': False, 'error': '缺少節點ID'}), 400
    
    nodes = load_nodes()
    if node_id not in nodes:
        return jsonify({'success': False, 'error': '節點不存在'}), 404
    
    node = nodes[node_id]
    
    # 檢查權限
    if role != 'admin':
        quotas = load_quotas()
        user_quota = quotas.get(user_id, {})
        allowed_nodes = user_quota.get('allowed_nodes', [])
        if node_id not in allowed_nodes:
            return jsonify({'success': False, 'error': '無權存取此節點'}), 403
    
    try:
        # 從 Node 獲取檔案列表
        response = requests.get(
            f"http://{node['host']}:{node['port']}/api/node/files/list",
            params={'user_id': user_id},
            timeout=10,
            cookies=request.cookies
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify(result), response.status_code
        elif response.status_code == 404:
            # 如果 Node 沒有這個端點，嘗試舊的方式
            # 從 Panel 資料庫獲取
            files = load_files()
            node_files = {k: v for k, v in files.items() if v.get('node_id') == node_id}
            if role != 'admin':
                node_files = {k: v for k, v in node_files.items() if v.get('user_id') == user_id}
            return jsonify({'success': True, 'files': node_files, 'source': 'panel'})
        else:
            return jsonify({'success': False, 'error': f'Node 返回錯誤'}), response.status_code
    except Exception as e:
        # 如果連接失敗，從 Panel 資料庫獲取
        files = load_files()
        node_files = {k: v for k, v in files.items() if v.get('node_id') == node_id}
        if role != 'admin':
            node_files = {k: v for k, v in node_files.items() if v.get('user_id') == user_id}
        return jsonify({'success': True, 'files': node_files, 'source': 'panel', 'error': str(e)})

@app.route('/api/node/folders', methods=['GET'])
@login_required
def list_node_folders():
    """從 Node 獲取資料夾列表"""
    user_id = session.get('user_id')
    role = session.get('role')
    node_id = request.args.get('node_id')
    path = request.args.get('path', '').strip()
    
    if not node_id:
        return jsonify({'success': False, 'error': '缺少節點ID'}), 400
    
    nodes = load_nodes()
    if node_id not in nodes:
        return jsonify({'success': False, 'error': '節點不存在'}), 404
    
    node = nodes[node_id]
    
    # 檢查權限
    if role != 'admin':
        quotas = load_quotas()
        user_quota = quotas.get(user_id, {})
        allowed_nodes = user_quota.get('allowed_nodes', [])
        if node_id not in allowed_nodes:
            return jsonify({'success': False, 'error': '無權存取此節點'}), 403
    
    try:
        response = requests.get(
            f"http://{node['host']}:{node['port']}/api/node/folder/list",
            params={'user_id': user_id, 'path': path},
            timeout=10,
            cookies=request.cookies
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify(result), response.status_code
        else:
            return jsonify({'success': False, 'error': '無法從 Node 獲取資料'}), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== 資料夾管理 API ====================

@app.route('/api/folder/delete', methods=['POST'])
@api_token_required('folder:delete')
@login_required
def delete_folder():
    user_id = session.get('user_id')
    data = request.get_json()
    node_id = data.get('node_id')
    folder_path = data.get('folder_path', '').strip()

    if not folder_path:
        return jsonify({'success': False, 'error': '無法刪除根目錄'}), 400

    nodes = load_nodes()
    if node_id not in nodes:
        return jsonify({'success': False, 'error': '節點不存在'}), 404

    node = nodes[node_id]

    try:
        response = requests.post(
            f"http://{node['host']}:{node['port']}/api/node/folder/delete",
            json={'user_id': user_id, 'folder_path': folder_path},
            timeout=10
        )
        result = response.json()
        
        # 如果刪除成功，更新用戶配額
        if result.get('success'):
            deleted_size = result.get('deleted_size', 0)
            if deleted_size > 0:
                quotas = load_quotas()
                if user_id in quotas:
                    quotas[user_id]['used'] = max(0, quotas[user_id].get('used', 0) - deleted_size)
                    save_quotas(quotas)
        
        return jsonify(result), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/folder/move', methods=['POST'])
@api_token_required('folder:write')
@login_required
def move_folder():
    user_id = session.get('user_id')
    data = request.get_json()
    node_id = data.get('node_id')
    source_path = data.get('source_path', '').strip()
    target_path = data.get('target_path', '').strip()

    if not source_path:
        return jsonify({'success': False, 'error': '來源路徑不能為空'}), 400

    nodes = load_nodes()
    if node_id not in nodes:
        return jsonify({'success': False, 'error': '節點不存在'}), 404

    node = nodes[node_id]

    try:
        response = requests.post(
            f"http://{node['host']}:{node['port']}/api/node/folder/move",
            json={'user_id': user_id, 'source_path': source_path, 'target_path': target_path},
            timeout=10
        )
        result = response.json()
        return jsonify(result), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/folder/create', methods=['POST'])
@api_token_required('folder:create')
@login_required
def create_folder():
    user_id = session.get('user_id')
    data = request.get_json()
    node_id = data.get('node_id')
    folder_name = data.get('folder_name', '').strip()
    current_path = data.get('path', '').strip()
    
    if not folder_name:
        return jsonify({'success': False, 'error': '請輸入資料夾名稱'}), 400
    
    if '..' in folder_name:
        return jsonify({'success': False, 'error': '無效的資料夾名稱'}), 400
    
    folder_path = current_path + '/' + folder_name if current_path else folder_name
    
    nodes = load_nodes()
    if node_id not in nodes:
        return jsonify({'success': False, 'error': '節點不存在'}), 404
    
    node = nodes[node_id]
    
    try:
        response = requests.post(
            f"http://{node['host']}:{node['port']}/api/node/folder/create",
            json={'user_id': user_id, 'folder_path': folder_path},
            timeout=10
        )
        result = response.json()
        return jsonify(result), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/folder/list', methods=['GET'])
@api_token_required('folder:read')
@login_required
def list_folders():
    user_id = session.get('user_id')
    node_id = request.args.get('node_id')
    path = request.args.get('path', '').strip()
    
    nodes = load_nodes()
    if node_id not in nodes:
        return jsonify({'success': False, 'error': '節點不存在'}), 404
    
    node = nodes[node_id]
    
    try:
        response = requests.get(
            f"http://{node['host']}:{node['port']}/api/node/folder/list",
            params={'user_id': user_id, 'path': path},
            timeout=10,
            cookies=request.cookies
        )
        result = response.json()
        
        # 轉換 Node 的回應格式以匹配前端期望
        if result.get('success'):
            folders = result.get('folders', [])
            files = result.get('files', [])
            
            # 合併為 items 陣列
            items = folders + files
            
            return jsonify({
                'success': True,
                'folders': folders,
                'files': files,
                'items': items
            }), response.status_code
        
        return jsonify(result), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== 檔案預覽 API ====================

@app.route('/api/file/preview/<path:file_path>', methods=['GET'])
@login_required
def preview_file(file_path):
    user_id = session.get('user_id')
    node_id = request.args.get('node_id')
    
    if not node_id:
        return jsonify({'success': False, 'error': '缺少 node_id 參數'}), 400
    
    nodes = load_nodes()
    
    if node_id not in nodes:
        return jsonify({'success': False, 'error': '節點不存在'}), 404
    
    node = nodes[node_id]
    
    # 檢查節點狀態
    current_time = time.time()
    last_heartbeat = node.get('last_heartbeat', 0)
    node_status = 'online' if current_time - last_heartbeat <= 90 else 'offline'
    
    if node_status == 'offline':
        return jsonify({'success': False, 'error': '節點離線'}), 503
    
    # 直接從 Node 獲取預覽
    node_token = node.get('token', '')
    node_token_id = node.get('token_id', '')
    
    try:
        response = requests.get(
            f"http://{node['host']}:{node['port']}/api/node/preview/{file_path}",
            params={'user_id': user_id},
            timeout=30,
            stream=True,
            headers={
                'X-Token-Id': node_token_id,
                'token': node_token
            }
        )
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            if content_type.startswith('image/'):
                return response.content, 200, {'Content-Type': content_type}
            elif content_type == 'application/pdf':
                return response.content, 200, {'Content-Type': content_type}
            else:
                return jsonify(response.json()), 200
        elif response.status_code == 404:
            return jsonify({'success': False, 'error': '檔案不存在'}), 404
        else:
            try:
                data = response.json()
                return jsonify(data), response.status_code
            except:
                return jsonify({'success': False, 'error': f'Node 返回錯誤: {response.status_code}'}), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'error': '無法連接節點'}), 500

# ==================== 路由 ====================

@app.route('/icon.png')
def serve_icon():
    """提供 icon.png 檔案"""
    icon_path = os.path.join(BASE_DIR, 'templates', 'icon.png')
    return send_file(icon_path, mimetype='image/png')

@app.route('/')
def file_manager():
    return render_template('drive.html')

@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

if __name__ == '__main__':
    init_database()
    print("HimCloud Panel 啟動中...")
    print("網盤界面: http://localhost:5000")
    print("後台管理: http://localhost:5000/admin")
    print("提示: 首次使用請執行 python init_admin.py 建立管理員帳號")
    app.run(host='0.0.0.0', port=5000, debug=True)
