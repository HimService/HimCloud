#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HimCloud 管理員帳號初始化腳本
用於建立第一個管理員帳號
"""

import os
import sys
import uuid
import hashlib
import sqlite3
import getpass

# 設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'data.db')

def get_db():
    """取得資料庫連線"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    """密碼雜湊"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_admin_user(username, password):
    """建立管理員帳號"""
    # 確保資料目錄存在
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # 初始化資料庫連線（確保資料表存在）
    conn = get_db()
    cursor = conn.cursor()
    
    # 檢查用戶表是否存在
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at REAL NOT NULL
        )
    ''')
    
    # 檢查配額表是否存在
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quotas (
            user_id TEXT PRIMARY KEY,
            quota INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            allowed_nodes TEXT DEFAULT '[]',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    
    # 檢查管理員是否已存在
    cursor.execute('SELECT COUNT(*) FROM users WHERE role = ?', ('admin',))
    admin_count = cursor.fetchone()[0]
    
    if admin_count > 0:
        print("\n❌ 錯誤：系統中已存在管理員帳號！")
        print("   如需重設密碼，請直接修改資料庫或刪除資料庫後重新執行。")
        conn.close()
        return False
    
    # 建立管理員帳號
    user_id = str(uuid.uuid4())
    admin_password = hash_password(password)
    
    try:
        cursor.execute(
            'INSERT INTO users (id, username, password, role, created_at) VALUES (?, ?, ?, ?, ?)',
            (user_id, username, admin_password, 'admin', __import__('time').time())
        )
        cursor.execute(
            'INSERT INTO quotas (user_id, quota, used, allowed_nodes) VALUES (?, ?, ?, ?)',
            (user_id, 0, 0, '[]')
        )
        conn.commit()
        conn.close()
        
        print("\n✅ 管理員帳號建立成功！")
        print(f"   帳號: {username}")
        print(f"   密碼: {'*' * len(password)}")
        print(f"\n   請牢記您的帳號密碼！")
        print(f"   登入網址: http://localhost:5000/admin")
        return True
        
    except sqlite3.IntegrityError:
        print(f"\n❌ 錯誤：帳號 '{username}' 已經存在！")
        conn.close()
        return False
    except Exception as e:
        print(f"\n❌ 錯誤：{str(e)}")
        conn.close()
        return False

def main():
    print("=" * 50)
    print("  HimCloud 管理員帳號初始化")
    print("=" * 50)
    print()
    
    # 檢查資料庫是否存在
    if os.path.exists(DB_PATH):
        conn = get_db()
        cursor = conn.cursor()
        
        # 檢查是否已有管理員
        try:
            cursor.execute('SELECT COUNT(*) FROM users WHERE role = ?', ('admin',))
            admin_count = cursor.fetchone()[0]
            conn.close()
            
            if admin_count > 0:
                print("❌ 錯誤：系統中已存在管理員帳號！")
                print("   如需重設密碼，請直接修改資料庫或刪除資料庫後重新執行。")
                sys.exit(1)
        except:
            conn.close()
    
    # 輸入帳號
    username = input("請輸入管理員帳號 [admin]: ").strip()
    if not username:
        username = "admin"
    
    # 輸入密碼
    while True:
        password = getpass.getpass("請輸入管理員密碼: ")
        if not password:
            print("❌ 錯誤：密碼不能為空！")
            continue
        
        password_confirm = getpass.getpass("請再次輸入密碼確認: ")
        if password != password_confirm:
            print("❌ 錯誤：兩次輸入的密碼不一致！")
            continue
        
        if len(password) < 4:
            print("❌ 錯誤：密碼長度至少需要 4 個字元！")
            continue
        
        break
    
    # 建立管理員
    success = create_admin_user(username, password)
    
    if success:
        print("\n" + "=" * 50)
        print("  初始化完成！")
        print("=" * 50)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
