# Affiliate MXH

Bản chạy thử cục bộ để quản lý Fanpage. Ba Fanpage ban đầu là Trạm AI, Tủ Đồ Hay và Có Gì Hay. Có thể thêm Fanpage trên giao diện.

Chạy bằng Python 3.10+.

```sh
python app.py
```

Mở http://127.0.0.1:8080. Dữ liệu nằm trong SQLite. Có thể đặt đường dẫn bằng biến môi trường `AFFILIATE_DB`.

Máy chủ thử nghiệm chỉ lắng nghe trên localhost. Tài khoản và phân quyền cần có trước khi triển khai cho nhiều người dùng.

Ở nhánh `feature/content-workflow`, bạn có thể lưu sản phẩm kèm link affiliate, tạo bài nháp cho từng Fanpage, duyệt bài và lưu lịch theo giờ Việt Nam. Lịch hiện được lưu trong SQLite. Tích hợp đăng bài Facebook sẽ cần kết nối riêng.

## Lập kế hoạch cảnh Reel

Tạo bản nháp, mở **Thêm cảnh Reel 9:16** rồi nhập prompt và thời lượng từng cảnh theo thứ tự. App hiển thị tổng thời lượng. Hãy kiểm tra kế hoạch trước khi duyệt bài. Tính năng này lưu kế hoạch cảnh, chưa gọi dịch vụ tạo video.

### Ví dụ bàn giao cho agent

Với Tủ Đồ Hay, xác nhận sản phẩm, ảnh gốc và link affiliate trước khi soạn cảnh. Khi mô tả cảnh, ghi hành động, góc máy và chi tiết phải giữ nguyên để video thể hiện đúng sản phẩm. Sau khi có clip, đối chiếu lại clip với ảnh gốc và link trước khi duyệt. Nếu thiếu ảnh gốc hoặc nhận ra sản phẩm sai, chuyển lại bước chọn sản phẩm.
