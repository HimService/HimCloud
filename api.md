# HimService API 文檔

## 目錄

1. [系統架構](#系統架構)
2. [認證方式](#認證方式)
3. [API 端點總覽](#api-端點總覽)
4. [認證 API](#認證-api)
5. [用戶管理 API](#用戶管理-api)
6. [節點管理 API](#節點管理-api)
7. [檔案管理 API](#檔案管理-api)
8. [資料夾管理 API](#資料夾管理-api)
9. [開發者 API Token](#開發者-api-token)
10. [錯誤碼說明](#錯誤碼說明)
11. [前後端溝通範例](#前後端溝通範例)

---

## 系統架構

HimService 採用分散式儲存架構，包含三個主要元件：

```
┌─────────────────────────────────────────────────────────────┐
│                        HimService 架構                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐│
│  │   前端網頁   │────▶│  Panel 端   │────▶│  Node 端    ││
│  │  (瀏覽器)   │◀────│  (Port 5000) │◀────│ (Port 5001) ││
│  └─────────────┘     └─────────────┘     └─────────────┘│
│        │                   │                   │           │
│        │                   │                   │           │
│        ▼                   ▼                   ▼           │
│   HTML/JS/CSS         REST API           實際檔案        │
│   使用者介面         業務邏輯            儲存空間         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 元件說明

| 元件 | 端口 | 功能說明 |
|------|------|----------|
| 前端網頁 | - | 使用 Bootstrap + JavaScript 構建的使用者介面 |
| Panel 端 | 5000 | 主控制器，負責用戶認證、節點管理、檔案協調 |
| Node 端 | 5001 | 儲存節點，負責實際的檔案儲存與讀取 |

### 資料儲存

- Panel 端使用 SQLite 資料庫 (`panel/data/data.db`)
- Node 端使用 SQLite 資料庫 (`node/data/node.db`)

---

## 節點綁定流程

HimService 使用兩步驟驗證機制綁定 Node 與 Panel：

```
┌──────────────────────────────────────────────────────────────┐
│                     節點綁定流程                            │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Panel 後台建立節點配置                                   │
│       │                                                      │
│       ▼                                                      │
│  2. Panel 生成 token_id + token                              │
│       │                                                      │
│       ▼                                                      │
│  3. 管理員取得配置檔案 (config.yml)                          │
│       │                                                      │
│       ▼                                                      │
│  4. Node 啟動 → 發送 token_id 驗證 (/api/node/verify)       │
│       │                                                      │
│       ▼                                                      │
│  5. 驗證通過 → 發送 token 進行綁定 (/api/node/bind)         │
│       │                                                      │
│       ▼                                                      │
│  6. 綁定成功，節點上線                                      │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 刪除節點

當管理員刪除節點時：
1. 從 `nodes` 表刪除節點
2. 從 `node_bindings` 表刪除綁定記錄
3. Node 下次連線時會因找不到 token_id 被拒絕

---

## 認證方式

HimService 支援兩種認證方式：

### 1. Session 認證（網頁登入）

適用於一般使用者透過瀏覽器操作。

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}
```

### 2. API Token 認證（開發者）

適用於開發者透過 API 程式操作。

```http
GET /api/file/list
X-API-Token: your_api_token_here
```

**權限說明：**

| 權限 | 說明 |
|------|------|
| `file:read` | 讀取檔案列表 |
| `file:upload` | 上傳檔案 |
| `file:download` | 下載檔案 |
| `file:delete` | 刪除檔案 |
| `file:move` | 移動檔案 |
| `file:preview` | 預覽檔案 |
| `folder:read` | 讀取資料夾列表 |
| `folder:list` | 列出資料夾內容 |
| `folder:create` | 建立資料夾 |
| `folder:delete` | 刪除資料夾 |
| `folder:write` | 移動資料夾 |
| `user:read` | 讀取用戶資訊 |
| `user:create` | 建立用戶 |
| `user:update` | 更新用戶 |
| `user:delete` | 刪除用戶 |
| `user:quota` | 設定用戶配額 |
| `node:read` | 讀取節點資訊 |
| `node:create` | 建立節點 |
| `node:update` | 更新節點 |
| `node:delete` | 刪除節點 |
| `node:config` | 產生節點配置 |
| `auth:login` | 登入驗證 |
| `auth:check` | 檢查登入狀態 |

---

## API 端點總覽

### 認證 API

| 方法 | 路徑 | 說明 | 認證方式 |
|------|------|------|----------|
| POST | /api/auth/login | 使用者登入 | 無 |
| POST | /api/auth/logout | 使用者登出 | Session |
| GET | /api/auth/check | 檢查登入狀態 | 無 |

### 用戶管理 API

| 方法 | 路徑 | 說明 | 認證方式 |
|------|------|------|----------|
| GET | /api/user/list | 列出所有用戶 | 管理者 + user:read |
| POST | /api/user/create | 建立新用戶 | 管理者 |
| GET | /api/user/{id} | 獲取用戶資訊 | 管理者 + user:read |
| PUT | /api/user/{id} | 更新用戶資料 | 管理者 + user:update |
| DELETE | /api/user/{id} | 刪除用戶 | 管理者 + user:delete |
| POST | /api/user/quota | 設定用戶配額 | 管理者 + user:quota |

### 節點管理 API

| 方法 | 路徑 | 說明 | 認證方式 |
|------|------|------|----------|
| POST | /api/node/verify | 驗證節點 token_id | 無 |
| POST | /api/node/bind | 綁定節點 | 無 |
| POST | /api/node/heartbeat | 節點心跳 | 無 |
| GET | /api/node/list | 列出所有節點 | 登入 + node:read |
| POST | /api/node/config | 建立節點設定 | 管理者 + node:config |
| DELETE | /api/node/{id} | 刪除節點 | 管理者 + node:delete |

### Node 端 API（內部使用）

| 方法 | 路徑 | 說明 | 認證方式 |
|------|------|------|----------|
| GET | /api/node/info | 獲取節點資訊 | Node Token |
| POST | /api/node/store | 儲存檔案 | Node Token |
| GET | /api/node/retrieve/{id} | 取得檔案 | Node Token |
| DELETE | /api/node/delete/{id} | 刪除檔案 | Node Token |
| GET | /api/node/files/list | 列出所有檔案 | Node Token |
| GET | /api/node/folder/list | 列出資料夾內容 | Node Token |
| POST | /api/node/folder/create | 建立資料夾 | Node Token |
| POST | /api/node/folder/delete | 刪除資料夾（會刪除內部所有內容） | Node Token |
| POST | /api/node/folder/move | 移動資料夾（會移動內部所有內容） | Node Token |
| POST | /api/node/file/move | 移動檔案 | Node Token |
| GET | /api/node/preview/{path} | 預覽檔案（圖片/PDF） | Node Token |

### 檔案管理 API

| 方法 | 路徑 | 說明 | 認證方式 |
|------|------|------|----------|
| POST | /api/file/upload | 上傳檔案 | 登入 + file:upload |
| GET | /api/file/list | 列出檔案 | 登入 + file:read |
| GET | /api/file/by-node/{node_id} | 按節點列出檔案 | 登入 |
| GET | /api/file/download/{id} | 下載檔案 | 登入 + file:download |
| GET | /api/file/preview/{path} | 預覽檔案（圖片/PDF） | 登入 + file:preview |
| DELETE | /api/file/{id} | 刪除檔案 | 登入 + file:delete |
| POST | /api/file/move | 移動檔案 | 登入 + file:move |

### 資料夾管理 API

| 方法 | 路徑 | 說明 | 認證方式 |
|------|------|------|----------|
| GET | /api/folder/list | 列出資料夾內容 | 登入 + folder:read |
| POST | /api/folder/create | 建立資料夾 | 登入 + folder:create |
| POST | /api/folder/delete | 刪除資料夾 | 登入 + folder:delete |
| POST | /api/folder/move | 移動資料夾 | 登入 + folder:write |

### 開發者 API Token

| 方法 | 路徑 | 說明 | 認證方式 |
|------|------|------|----------|
| GET | /api/dev/token/list | 列出所有 Token | 管理者 |
| POST | /api/dev/token/create | 建立新 Token | 管理者 |
| PUT | /api/dev/token/{id} | 更新 Token | 管理者 |
| DELETE | /api/dev/token/{id} | 刪除 Token | 管理者 |
| POST | /api/dev/token/{id}/regenerate | 重新產生 Token | 管理者 |
| GET | /api/dev/permissions | 獲取可用權限列表 | 無 |

---

## 節點管理 API 詳細說明

### POST /api/node/verify

驗證節點 token_id（第一步）。

**請求：**
```json
{
  "token_id": "節點的token_id"
}
```

**回應（成功）：**
```json
{
  "success": true,
  "message": "Token ID 驗證成功，請繼續發送 Token 進行綁定"
}
```

**回應（失敗）：**
```json
{
  "success": false,
  "error": "Token ID 不存在，請聯絡管理員取得正確配置"
}
```

---

### POST /api/node/bind

綁定節點（第二步）。

**請求：**
```json
{
  "token_id": "節點的token_id",
  "token": "節點的token",
  "uuid": "可選的UUID",
  "name": "節點名稱",
  "host": "節點主機",
  "port": 5001,
  "capacity": 1073741824000
}
```

**回應（成功）：**
```json
{
  "success": true,
  "message": "節點綁定成功",
  "node_id": "節點ID"
}
```

---

### POST /api/node/heartbeat

節點心跳。

**請求：**
```json
{
  "token_id": "節點的token_id",
  "token": "節點的token",
  "capacity": 1073741824000,
  "used": 536870912000
}
```

---

### DELETE /api/node/{node_id}

刪除節點（同時刪除綁定，節點下次無法再連線）。

---

## 認證 API

### POST /api/auth/login

使用者登入。

**請求：**
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**回應（成功）：**
```json
{
  "success": true,
  "user": {
    "id": "admin",
    "username": "admin",
    "role": "admin"
  }
}
```

---

## 用戶管理 API

### GET /api/user/list

列出所有用戶（需要管理者權限）。

**請求 Headers：**
```http
X-API-Token: your_token_here
```

**回應：**
```json
{
  "success": true,
  "users": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "username": "admin",
      "role": "admin",
      "created_at": 1704067200,
      "storage_quota": 10737418240,
      "storage_used": 1048576
    }
  ]
}
```

---

### POST /api/user/create

建立新用戶（需要管理者權限）。

**請求：**
```json
{
  "username": "newuser",
  "password": "password123",
  "role": "user"
}
```

---

## 節點管理 API

### GET /api/node/list

列出所有節點。

**請求 Headers：**
```http
X-API-Token: your_token_here
```

**回應：**
```json
{
  "success": true,
  "nodes": {
    "node_123": {
      "id": "node_123",
      "name": "Storage Node 1",
      "host": "192.168.1.100",
      "port": 5001,
      "status": "online",
      "capacity": 1073741824000,
      "used": 536870912000,
      "token_id": "token_id_xxx"
    }
  }
}
```

---

### POST /api/node/config

建立新節點設定檔（需要管理者權限）。

**請求：**
```json
{
  "name": "New Node",
  "connection_url": "https://node.example.com:5001",
  "storage_limit": 107374182400,
  "redundancy": 0,
  "max_file_size": 104857600,
  "heartbeat_interval": 30,
  "panel_url": "http://localhost:5000"
}
```

**回應：**
```json
{
  "success": true,
  "token_id": "new_token_id",
  "token": "abc123...",
  "config_content": "# HimService Node 配置檔案\n..."
}
```

---

## 檔案管理 API

### POST /api/file/upload

上傳檔案。

**請求 (Multipart Form Data)：**
```
POST /api/file/upload
Content-Type: multipart/form-data

file: (二進制檔案資料)
node_id: (可選，指定上傳到哪個節點)
```

**回應：**
```json
{
  "success": true,
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "node": "Storage Node 1"
}
```

---

### GET /api/file/list

列出所有檔案。

**回應：**
```json
{
  "success": true,
  "files": {
    "file_123": {
      "id": "file_123",
      "name": "document.pdf",
      "size": 1048576,
      "node_id": "node_123",
      "node_name": "Storage Node 1",
      "user_id": "user_123",
      "uploaded_at": 1704067200
    }
  }
}
```

---

### GET /api/file/download/{id}

下載檔案。

---

### GET /api/file/preview/{path}

預覽檔案（圖片或 PDF）。

**參數：**
- `node_id` (Query String) - 節點 ID（必填）

**請求：**
```
GET /api/file/preview/image.jpg?node_id=node_123
```

**回應（成功）：**
- 返回圖片二進制數據，Content-Type 為圖片 MIME 類型
- 或返回 PDF 二進制數據，Content-Type 為 application/pdf

**回應（失敗）：**
```json
{
  "success": false,
  "error": "缺少 node_id 參數"
}
```

```json
{
  "success": false,
  "error": "節點不存在"
}
```

```json
{
  "success": false,
  "error": "節點離線"
}
```

```json
{
  "success": false,
  "error": "檔案不存在"
}
```

---

### DELETE /api/file/{id}

刪除檔案。

---

### POST /api/file/move

移動檔案到指定資料夾。

**請求：**
```json
{
  "file_id": "file_123",
  "node_id": "node_123",
  "target_folder": "/myfolder"
}
```

---

## 資料夾管理 API

### GET /api/folder/list

列出資料夾內容。

**請求：**
```
GET /api/folder/list?node_id=node_123&path=/myfolder
```

**回應：**
```json
{
  "success": true,
  "folders": [
    {
      "name": "subfolder",
      "path": "myfolder/subfolder",
      "type": "folder"
    }
  ],
  "files": [
    {
      "id": "file_123",
      "name": "file.txt",
      "path": "myfolder/file.txt",
      "size": 1024,
      "type": "file"
    }
  ],
  "items": [
    {
      "name": "subfolder",
      "type": "folder"
    },
    {
      "name": "file.txt",
      "type": "file",
      "size": 1024
    }
  ]
}
```

---

### POST /api/folder/create

建立資料夾。

**請求：**
```json
{
  "node_id": "node_123",
  "folder_name": "newfolder",
  "path": "/myfolder"
}
```

---

### POST /api/folder/delete

刪除資料夾。

**請求：**
```json
{
  "node_id": "node_123",
  "folder_path": "/myfolder/oldfolder"
}
```

**回應：**
```json
{
  "success": true,
  "deleted_size": 1048576
}
```

**注意：** 刪除資料夾時會自動扣除用戶的已使用空間配額。

---

### POST /api/folder/move

移動資料夾（包含內部的子資料夾和檔案）。

**請求：**
```json
{
  "node_id": "node_123",
  "source_path": "/myfolder/oldfolder",
  "target_path": "/newfolder"
}
```

---

## 開發者 API Token

### GET /api/dev/token/list

列出所有 API Token（需要管理者權限）。

### POST /api/dev/token/create

建立新的 API Token。

**請求：**
```json
{
  "name": "Developer Token",
  "permissions": ["file:read", "file:upload", "file:download"],
  "enabled": true
}
```

### DELETE /api/dev/token/{id}

刪除 API Token。

### POST /api/dev/token/{id}/regenerate

重新產生 API Token。

---

## 錯誤碼說明

| HTTP 狀態碼 | 錯誤訊息 | 說明 |
|-------------|----------|------|
| 400 | 無效的請求 | 請求格式錯誤或參數不正確 |
| 401 | 請先登入 / 需要 API Token | 未認證或認證失敗 |
| 403 | 權限不足 | 沒有足夠的權限執行此操作 |
| 404 | 資源不存在 | 找不到請求的資源 |
| 500 | 伺服器錯誤 | 伺服器發生內部錯誤 |

---

## 前後端溝通範例

### 使用 Python 請求

```python
import requests

BASE_URL = 'http://localhost:5000'
API_TOKEN = 'your_api_token_here'

headers = {'X-API-Token': API_TOKEN}

# 登入並取得 Session
login_response = requests.post(
    f'{BASE_URL}/api/auth/login',
    json={'username': 'admin', 'password': 'admin123'}
)
cookies = login_response.cookies

# 取得檔案列表
def list_files():
    response = requests.get(f'{BASE_URL}/api/file/list', headers=headers)
    return response.json()

# 上傳檔案
def upload_file(file_path):
    with open(file_path, 'rb') as f:
        files = {'file': f}
        response = requests.post(
            f'{BASE_URL}/api/file/upload',
            files=files,
            headers={'X-API-Token': API_TOKEN}
        )
    return response.json()
```

### 使用 cURL

```bash
# 登入
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  -c cookies.txt

# 取得檔案列表
curl http://localhost:5000/api/file/list \
  -b cookies.txt

# 使用 API Token
curl http://localhost:5000/api/file/list \
  -H "X-API-Token: your_token_here"
```

---

## 附錄

### 預設帳號

- **帳號：** admin
- **密碼：** 首次使用需執行 `python init_admin.py` 建立

### 預設端口

- **Panel 端：** 5000
- **Node 端：** 5001

### 資料儲存位置

- **Panel 資料庫：** `panel/data/data.db`
- **Node 資料庫：** `node/data/node.db`
- **Node 儲存目錄：** `node/storage/`

### 初始化

```bash
# Panel 端
cd panel
python init_admin.py  # 建立管理員帳號
python app.py         # 啟動 Panel

# Node 端
cd node
python app.py         # 啟動 Node（會自動綁定到 Panel）
```

---

## 功能說明

### 資料夾管理
- 支援建立、刪除資料夾
- 支援移動資料夾（包含內部子資料夾和檔案）
- 支援資料夾層級導航
- 顯示麵包屑導航

### 檔案操作
- 支援拖拽上傳
- 支援拖拽移動檔案到資料夾
- 支援圖片、影片預覽
- 支援批量操作（多選刪除、移動、下載）
- 支援 Shift + 點擊多選

### 權限控制
- 用戶配額管理
- 節點訪問控制
- API Token 權限細粒度控制

---

*文檔最後更新時間：2026年2月*
