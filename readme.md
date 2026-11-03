# TÀI LIỆU BÀN GIAO
## DOCX DOCUMENT PROCESSING PIPELINE

**Hệ thống:** DOCX Document Processing Pipeline  
**Mục đích:** Chuẩn hóa tài liệu DOCX có cấu trúc bảng phức tạp thành dữ liệu text có ngữ nghĩa, phục vụ hệ thống RAG/Chatbot.  
**Nguồn dữ liệu:** Azure Blob Storage  
**Phiên bản:** UAT  
**Ngày bàn giao:** 07/10/2026

---

# 1. MỤC ĐÍCH HỆ THỐNG

Pipeline được xây dựng nhằm xử lý các tài liệu DOCX có nội dung dạng bảng phức tạp, đặc biệt các bảng có:

- merged cells;
- nhiều dòng/cột;
- cấu trúc bảng không chuẩn;
- nội dung bị phân mảnh khi trích xuất trực tiếp;
- bảng cần hiểu ngữ nghĩa trước khi đưa vào hệ thống RAG.

Mục tiêu của pipeline là:

1. Nhận tài liệu DOCX từ Azure Blob Storage INPUT.
2. Phát hiện tài liệu mới hoặc có thay đổi.
3. Chỉ xử lý những tài liệu thực sự cần xử lý.
4. Trích xuất và tái cấu trúc nội dung bảng bằng LLM.
5. Thay thế bảng trong DOCX bằng nội dung text có ngữ nghĩa.
6. Lưu tài liệu đã xử lý vào Azure Blob Storage OUTPUT.
7. Giữ nguyên tên file và metadata nguồn.
8. Xóa OUTPUT tương ứng khi file INPUT bị xóa.
9. Hạn chế tối đa việc gọi LLM lại đối với tài liệu không thay đổi.
10. Lưu log mỗi lần chạy để phục vụ UAT và troubleshooting.

---

# 2. KIẾN TRÚC TỔNG QUAN

```text
SharePoint
    │
    │ Đồng bộ tài liệu
    ▼
Azure Blob Storage
INPUT Container
    │
    │ Document Pipeline
    ▼
Change Detection
    │
    ├── NEW
    ├── MODIFIED
    ├── UNCHANGED
    └── DELETED
    │
    ▼
Download DOCX
    │
    ▼
Local Temporary Storage
temp/
    │
    ▼
DOCX Processing
    │
    ├── Layout Extraction
    ├── Table Reconstruction
    ├── LLM
    ├── Normalize
    └── Replace Table → Semantic Text
    │
    ▼
temp_processed/
    │
    ▼
Azure Blob Storage
OUTPUT Container
    │
    ▼
AI Search / RAG
    │
    ▼
Chatbot
```

---

# 3. CẤU TRÚC SOURCE CODE

Project hiện tại:

```text
document-pipeline/
│
├── src/
│   ├── blob_storage.py
│   ├── docx_processor.py
│   └── pipeline.py
│
├── run_uat.py
├── requirements.txt
├── local.settings.json
│
├── logs/
│
├── temp/
└── temp_processed/
```

## 3.1. `src/blob_storage.py`

Chịu trách nhiệm giao tiếp với Azure Blob Storage.

Các chức năng chính:

- kết nối Azure Blob Storage;
- list blob;
- list DOCX;
- lấy metadata và ETag;
- download blob;
- upload file;
- delete blob;
- cập nhật metadata.

---

## 3.2. `src/docx_processor.py`

Chịu trách nhiệm xử lý nội dung DOCX.

Input:

```text
DOCX gốc
```

Output:

```text
DOCX đã xử lý
```

Các bước xử lý chính:

```text
DOCX
  ↓
Layout / structure extraction
  ↓
Xác định bảng cần reconstruction
  ↓
LLM table reconstruction
  ↓
Normalize semantic text
  ↓
Thay bảng bằng text
  ↓
DOCX output
```

Mục tiêu là giữ nguyên nội dung văn bản thông thường và chỉ xử lý phần bảng cần chuyển đổi.

---

## 3.3. `src/pipeline.py`

Đây là module điều phối chính.

Chịu trách nhiệm:

- lấy danh sách INPUT;
- lấy danh sách OUTPUT;
- change detection;
- xác định file cần xử lý;
- download;
- gọi `DocxProcessor`;
- upload OUTPUT;
- cập nhật metadata;
- xử lý file bị xóa;
- cleanup temporary files;
- thống kê kết quả.

---

## 3.4. `run_uat.py`

Entry point để chạy UAT.

Thực hiện:

1. đọc `local.settings.json`;
2. khởi tạo INPUT Blob client;
3. khởi tạo OUTPUT Blob client;
4. khởi tạo `DocumentPipeline`;
5. chạy `sync_blobs()`;
6. ghi kết quả ra terminal;
7. lưu log `.txt`.

Chạy:

```bash
python run_uat.py
```

---

# 4. AZURE BLOB STORAGE

Pipeline sử dụng mô hình hai container:

```text
INPUT CONTAINER
    ↓
Xử lý
    ↓
OUTPUT CONTAINER
```

## INPUT

Chứa tài liệu DOCX nguồn được đồng bộ từ SharePoint.

## OUTPUT

Chứa tài liệu DOCX đã được xử lý.

### Quy tắc tên file

Tên file trên OUTPUT giữ nguyên tên file trên INPUT.

Ví dụ:

```text
INPUT:
4051.LND.2026(2) Quy dinh he thong chuc danh....docx

OUTPUT:
4051.LND.2026(2) Quy dinh he thong chuc danh....docx
```

Điều này đảm bảo tên file nguồn được giữ nguyên cho các bước downstream và tham chiếu nguồn của chatbot.

---

# 5. CƠ CHẾ CHANGE DETECTION

Pipeline không xử lý lại toàn bộ tài liệu ở mỗi lần chạy.

Change detection dựa trên:

```text
INPUT ETag
        ↕
OUTPUT metadata.source_etag
```

`OUTPUT ETag` của chính OUTPUT blob không được dùng để xác định nội dung INPUT có thay đổi hay không.

---

## 5.1. NEW

Điều kiện:

```text
INPUT tồn tại
OUTPUT không tồn tại
```

Kết quả:

```text
NEW
→ Download
→ Process
→ LLM
→ Upload OUTPUT
```

---

## 5.2. MODIFIED

Điều kiện:

```text
INPUT ETag != OUTPUT metadata.source_etag
```

Kết quả:

```text
MODIFIED
→ Download
→ Process
→ LLM
→ Upload lại OUTPUT
→ cập nhật source_etag
```

Chỉ trường hợp nội dung nguồn thay đổi mới cần chạy lại quá trình xử lý LLM.

---

## 5.3. UNCHANGED

Điều kiện:

```text
INPUT ETag == OUTPUT metadata.source_etag
```

Kết quả:

```text
UNCHANGED
→ SKIP
→ Không download
→ Không gọi LLM
```

Đây là cơ chế chính để tiết kiệm thời gian và chi phí LLM.

---

## 5.4. DELETED

Điều kiện:

```text
OUTPUT tồn tại
INPUT không còn
```

Kết quả:

```text
DELETED
→ Delete OUTPUT
```

Không cần chạy DOCX processing.

---

# 6. QUẢN LÝ METADATA

Metadata của INPUT được giữ lại khi tạo OUTPUT.

Cách xử lý:

```text
INPUT metadata
      +
source_etag
      ↓
OUTPUT metadata
```

Ví dụ:

```text
INPUT metadata:
    category = VBLQ
    document_type = QuyTrinh
    year = 2026

INPUT ETag:
    abc123
```

OUTPUT:

```text
category = VBLQ
document_type = QuyTrinh
year = 2026
source_etag = abc123
```

## Ý nghĩa của `source_etag`

`source_etag` là ETag của **INPUT blob tại thời điểm OUTPUT được tạo/cập nhật**.

Không được nhầm với ETag của OUTPUT blob.

---

# 7. ĐỒNG BỘ METADATA

Trong trường hợp OUTPUT đã tồn tại và:

```text
INPUT ETag == OUTPUT source_etag
```

nhưng OUTPUT thiếu hoặc có metadata không đúng so với INPUT, pipeline có thể cập nhật metadata mà **không chạy lại LLM**.

Luồng:

```text
ETag giống nhau
      ↓
Nội dung không thay đổi
      ↓
Không cần LLM
      ↓
Kiểm tra metadata
      ↓
Metadata thiếu/sai?
      │
      ├── Có → Update metadata
      │
      └── Không → SKIP
```

Nguyên tắc:

> ETag quyết định việc có cần xử lý nội dung/LLM hay không. Metadata được kiểm tra độc lập.

Điều này tránh việc phải process lại hàng loạt tài liệu chỉ vì OUTPUT trước đó thiếu metadata.

---

# 8. LOCAL TEMPORARY STORAGE

Pipeline sử dụng hai thư mục tạm:

```text
temp/
temp_processed/
```

## `temp/`

Chứa DOCX download từ INPUT trong quá trình xử lý.

## `temp_processed/`

Chứa DOCX sau khi `DocxProcessor` xử lý xong, trước khi upload lên OUTPUT.

---

## 8.1. Cleanup

Sau khi:

```text
Process
  ↓
Upload OUTPUT thành công
```

pipeline xóa:

```text
temp/<file>
temp_processed/<file>
```

Nếu process hoặc upload thất bại, file temporary được giữ lại để phục vụ troubleshooting.

---

## 8.2. Local filename

Tên file local có thể được rút ngắn/hash để tránh giới hạn path của Windows đối với các DOCX có tên rất dài.

Ví dụ:

```text
Azure Blob:
4051.LND.2026(2) Quy dinh he thong chuc danh va mo ta cong viec....docx

Local:
7f82c9e1a3b45678.docx
```

Việc rút ngắn này chỉ áp dụng cho local temporary file.

Tên Blob INPUT/OUTPUT và metadata nguồn vẫn giữ tên file gốc.

Do đó không ảnh hưởng đến source/citation của chatbot.

---

# 9. XỬ LÝ BẢNG BẰNG LLM

Mục tiêu của LLM không phải tạo lại toàn bộ DOCX.

LLM chủ yếu được sử dụng để:

```text
Table structure
      ↓
Semantic understanding
      ↓
Semantic text
```

Ví dụ bảng có merged cells hoặc nhiều dòng/cột sẽ được chuyển thành text có ngữ nghĩa để hệ thống RAG có thể tìm kiếm và hiểu nội dung tốt hơn.

Các đoạn text thông thường của DOCX không cần đưa qua LLM chỉ để chuyển đổi bảng.

---

# 10. NGUYÊN TẮC TIẾT KIỆM TOKEN

Pipeline ưu tiên tránh gọi LLM khi không cần thiết.

| Trạng thái | LLM |
|---|---:|
| NEW | Có |
| MODIFIED | Có |
| UNCHANGED | Không |
| DELETED | Không |
| Chỉ thiếu metadata | Không |

Nhờ đó khi pipeline chạy định kỳ trên số lượng lớn tài liệu, chỉ các file mới/thay đổi mới phát sinh chi phí xử lý LLM.

---

# 11. LOG VẬN HÀNH

Mỗi lần chạy UAT tạo một file log trong:

```text
logs/
```

Ví dụ:

```text
logs/
└── pipeline_20261007_095900.txt
```

Log đồng thời được:

```text
print()
   ↓
Terminal
   +
TXT log
```

Do đó không cần thay đổi toàn bộ các `print()` hiện có trong source code.

---

# 12. NỘI DUNG LOG

Log bao gồm:

- INPUT container;
- OUTPUT container;
- danh sách file đang xử lý;
- trạng thái NEW/MODIFIED/UNCHANGED;
- quá trình PROCESS;
- upload;
- delete;
- lỗi từng file;
- summary cuối job.

Ví dụ:

```text
AZURE BLOB PIPELINE SUMMARY
New       : 2
Modified  : 5
Unchanged : 140
Deleted   : 1
Failed    : 0
```

Khi `Failed > 0`, mở file log để xác định:

```text
Tên file lỗi
Error message
```

và phục vụ troubleshooting.

---

# 13. XỬ LÝ LỖI

Pipeline xử lý lỗi theo từng file.

Nếu một file lỗi:

```text
File A → SUCCESS
File B → FAILED
File C → SUCCESS
```

thì pipeline vẫn tiếp tục xử lý các file còn lại.

Summary cuối job phản ánh:

```text
Failed : 1
```

Temporary file của file lỗi được giữ lại để debug.

---

# 14. CẤU HÌNH

Cấu hình local được đặt trong:

```text
local.settings.json
```

Các cấu hình chính:

```text
AZURE_STORAGE_CONNECTION_STRING
AZURE_STORAGE_INPUT_CONTAINER
AZURE_STORAGE_OUTPUT_CONTAINER
```

Không hard-code connection string hoặc thông tin bảo mật vào source code.

`local.settings.json` phải được quản lý theo chính sách bảo mật của môi trường và không commit secret lên repository.

---

# 15. QUY TRÌNH CHẠY UAT

## Bước 1 – Kiểm tra INPUT

Đảm bảo các DOCX cần xử lý đã có trong INPUT container.

## Bước 2 – Chạy pipeline

```bash
python run_uat.py
```

## Bước 3 – Kiểm tra summary

Quan sát:

```text
New
Modified
Unchanged
Deleted
Failed
```

## Bước 4 – Nếu Failed > 0

Mở:

```text
logs/pipeline_YYYYMMDD_HHMMSS.txt
```

Tìm:

```text
✗ Failed
```

để xác định file và lỗi.

## Bước 5 – Kiểm tra OUTPUT

Đảm bảo:

- file NEW đã xuất hiện;
- file MODIFIED đã được cập nhật;
- file UNCHANGED không bị process lại;
- file DELETED không còn trên OUTPUT.

---

# 16. KẾT QUẢ UAT ĐÃ KIỂM TRA

Pipeline đã kiểm tra các trường hợp chính:

### New file

```text
INPUT có file mới
→ OUTPUT chưa có
→ Process
→ Upload
```

Kết quả: PASS.

### Modified file

```text
INPUT ETag thay đổi
→ Process lại
→ cập nhật OUTPUT
```

Kết quả: PASS.

### Unchanged file

```text
INPUT ETag == OUTPUT source_etag
→ Skip
```

Kết quả: PASS.

### Deleted file

```text
INPUT không còn
→ Delete OUTPUT
```

Kết quả: PASS.

### Metadata

INPUT metadata được giữ lại khi tạo/cập nhật OUTPUT.

Trường hợp OUTPUT thiếu metadata nhưng nội dung không thay đổi được xử lý theo hướng:

```text
Update metadata
→ Không gọi LLM
```

---

# 17. CÁC LƯU Ý QUAN TRỌNG

## 17.1. Không dùng OUTPUT ETag để so sánh INPUT

Không sử dụng:

```text
INPUT ETag ↔ OUTPUT ETag
```

Mà sử dụng:

```text
INPUT ETag ↔ OUTPUT metadata.source_etag
```

---

## 17.2. Không đổi tên Blob OUTPUT thành tên local

Tên local có thể hash/rút ngắn.

Tên OUTPUT Blob phải giữ tên nguồn để đảm bảo:

- traceability;
- metadata;
- source reference;
- downstream AI Search;
- chatbot citation.

---

## 17.3. Không xóa temporary file trước khi upload thành công

Chỉ cleanup sau:

```text
Process SUCCESS
+
Upload SUCCESS
```

Nếu lỗi thì giữ temporary file để debug.

---

# 18. LUỒNG END-TO-END

Luồng hoàn chỉnh:

```text
                    SHAREPOINT
                        │
                        │ Sync
                        ▼
              ┌───────────────────┐
              │  BLOB INPUT       │
              │                   │
              │ DOCX + Metadata   │
              └─────────┬─────────┘
                        │
                        ▼
                List DOCX + ETag
                        │
                        ▼
                CHANGE DETECTION
                        │
        ┌───────────────┼────────────────┐
        │               │                │
       NEW           MODIFIED        UNCHANGED
        │               │                │
        └───────┬───────┘                │
                │                        │
                ▼                        ▼
          Download DOCX               Check
                │                    Metadata
                ▼                        │
             temp/                 ┌─────┴─────┐
                │                  │           │
                ▼                thiếu       đủ
          DOCX PROCESSING          │           │
                │                  ▼           ▼
                │             Update Meta    SKIP
                ▼
       Table Reconstruction
                │
                ▼
              LLM
                │
                ▼
       Semantic Text / DOCX
                │
                ▼
       temp_processed/
                │
                ▼
          Upload OUTPUT
                │
                ▼
        Preserve Metadata
                │
                ▼
             Cleanup
                │
                ▼
         BLOB OUTPUT
                │
                ▼
       AI Search / RAG
                │
                ▼
             Chatbot


        OUTPUT tồn tại
        INPUT không còn
                │
                ▼
          DELETE OUTPUT
```

---

# 19. TRÁCH NHIỆM VẬN HÀNH

### Người vận hành cần kiểm tra

1. INPUT Blob có tài liệu cần xử lý.
2. Connection/configuration hợp lệ.
3. Job chạy thành công.
4. `Failed = 0` hoặc các lỗi đã được xử lý.
5. OUTPUT có đủ tài liệu.
6. Không có file bị process lại không cần thiết.
7. Log được lưu lại theo từng lần chạy.

### Khi có lỗi

Ưu tiên kiểm tra theo thứ tự:

```text
1. logs/
2. tên file bị Failed
3. Error message
4. temp/
5. temp_processed/
6. Azure Blob INPUT/OUTPUT
7. metadata + source_etag
```

---

# 20. TRẠNG THÁI BÀN GIAO

Pipeline hiện đã hoàn thành các chức năng cốt lõi:

- [x] Azure Blob INPUT
- [x] Azure Blob OUTPUT
- [x] DOCX download
- [x] DOCX processing
- [x] Table reconstruction
- [x] LLM processing
- [x] Upload OUTPUT
- [x] Metadata preservation
- [x] ETag-based change detection
- [x] New file processing
- [x] Modified file processing
- [x] Unchanged file skipping
- [x] Deleted file synchronization
- [x] Metadata-only update
- [x] Temporary file cleanup
- [x] UAT logging
- [x] UAT kiểm tra các trường hợp chính

Pipeline sẵn sàng cho bước tiếp theo là tích hợp với luồng downstream:

```text
OUTPUT DOCX
    ↓
Chunking
    ↓
Embedding
    ↓
Azure AI Search
    ↓
RAG / Chatbot
```

---

# 21. KẾT LUẬN

Pipeline được thiết kế theo nguyên tắc:

> **Chỉ xử lý lại tài liệu khi nội dung nguồn thực sự thay đổi; metadata được quản lý độc lập với nội dung.**

Cơ chế ETag giúp giảm việc xử lý và gọi LLM không cần thiết. Metadata nguồn được bảo toàn để phục vụ truy xuất và tham chiếu tài liệu ở các bước downstream.

Local temporary storage chỉ phục vụ quá trình xử lý trung gian và không ảnh hưởng đến tên file nguồn, tên file OUTPUT hoặc source reference của chatbot.