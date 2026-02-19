# HimCloud 雲端硬碟系統

一個分散式雲端硬碟系統，採用 Panel->Node 架構。

## 系統架構

```
┌─────────────────────────────────────────────────────────────┐
│                        HimService                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐    │
│  │   前端網頁   │───▶│  Panel 端   │───▶│  Node 端    │    │
│  │   (瀏覽器)   │◀───│(Port 5000)  │◀───│ (Port 5001) │    │
│  └─────────────┘     └─────────────┘     └─────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

- **Panel 端**：主控制器，負責用戶認證、節點管理、檔案協調
- **Node 端**：儲存節點，負責實際的檔案儲存與讀取
- **前端網頁**：使用 Bootstrap + JavaScript 構建的使用者介面

## 功能特色

- ✅ 分散式儲存架構
- ✅ 多節點支援（一個 Panel 可連接多個 Node）
- ✅ 用戶管理與配額控制(允許設定用戶存儲配額)
- ✅ 開發者 API Token 支援
- ✅ 帳戶控制系統
- ✅ 準確的節點綁定機制（兩步驟驗證）
- ✅ 資料夾管理
- ✅ 檔案拖拽移動
- ✅ 圖片/影片預覽
- ✅ 批量操作功能（多選刪除、移動、下載）

## 環境需求

- Python 3.7+
- requirements.txt

## 安裝

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 建立第一個面板帳號

```bash
cd panel
python init_admin.py
```

按照提示輸入管理員帳號和密碼。

### 3. 啟動 Panel

```bash
cd panel
python app.py
```

訪問 http://localhost:5000

### 4. 配置 Node（可選）

在後台管理頁面新增節點，取得配置文件後：
1. 將配置複製到 Node 的 `config.yml`
2. 啟動 Node：

```bash
cd node
python app.py
```

Node 會自動與 Panel 綁定。

## 使用指南

### 登入後台

- **網址**：http://localhost:5000/admin
- **帳號密碼**：首次使用須執行 `init_admin.py` 建立

### 管理節點

1. 登入後台
2. 進入「節點管理」
3. 點擊「新增節點」
4. 填寫節點資訊並建立
5. 將配置檔案提供給 Node 使用

### 刪除節點

在後台刪除節點時，會同時刪除綁定記錄，該 Node 將無法再次連線，除非重新創建token。

### 開發者 API

在後台「開發者 API」頁面可以：
- 建立 API Token
- 設定權限
- 管理 Token

API 使用方式：
```http
X-API-Token: your_token_here
```

## API Token 權限

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

## 節點綁定流程

```
1. Panel 後台建立節點配置
         │
         ▼
2. Panel 生成 token_id + token
         │
         ▼
3. 管理員取得配置檔案
         │
         ▼
4. Node 發送 token_id 驗證
         │
         ▼
5. 驗證通過，發送 token 綁定
         │
         ▼
6. 綁定成功，節點上線
```

## 資料儲存

- **Panel 資料庫**：`panel/data/data.db`
- **Node 資料庫**：`node/data/node.db`
- **Node 儲存數據目錄**：`node/storage/`

## 文件

- [API 文檔](api.md) - 完整的 API 端點說明

## 預設端口

- Panel：5000
- Node：5001

##  License

請見 License
