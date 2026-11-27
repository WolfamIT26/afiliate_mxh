# Affiliate MXH

Bản chạy thử cục bộ để quản lý Fanpage. Ba Fanpage ban đầu là Trạm AI, Tủ Đồ Hay và Có Gì Hay. Có thể thêm Fanpage trên giao diện.

Chạy bằng Python 3.10+.

```sh
python app.py
```

Mở http://127.0.0.1:8080. Dữ liệu nằm trong SQLite. Có thể đặt đường dẫn bằng biến môi trường `AFFILIATE_DB`.

Máy chủ thử nghiệm chỉ lắng nghe trên localhost. Tài khoản và phân quyền cần có trước khi triển khai cho nhiều người dùng.

## Quản lý nhiều Fanpage

Mở **Fanpage** để thêm trang, tìm theo tên hoặc Page ID, lọc theo nhóm và trạng thái, hoặc cập nhật các trang đã chọn. Trong cài đặt từng Fanpage, lưu hồ sơ thương hiệu, chủ đề, nguồn, CTA, quy tắc nội dung và CSKH. Dùng **Lưu cấu hình hiện tại làm mẫu** để dùng lại quy tắc nội dung khi thêm trang khác. Mẫu giữ nhóm và quy tắc, còn tên, Page ID và nhận diện được nhập riêng.

**Hôm nay** tổng hợp bản nháp và lịch sắp tới. **Lịch đăng** hiển thị lịch 7 ngày theo từng Fanpage hoặc toàn hệ thống (giờ Việt Nam). Bấm vào lịch để mở bài và hủy lịch nếu cần. Khi tạm dừng hoặc lưu trữ một trang, lịch cũ được giữ và đánh dấu. Trang lưu trữ cũng không nhận bài nháp hoặc phiếu mới. Lịch được lưu cục bộ trong SQLite.

### Kiểm tra kết nối Facebook

Lưu Facebook Page ID trong cài đặt trang. Trên máy chạy app, đặt `AFFILIATE_FB_PAGE_TOKEN_<PAGE_ID>` cho từng trang và `AFFILIATE_FB_APP_TOKEN` cho ứng dụng Meta. Nếu một trang thuộc ứng dụng Meta khác, đặt riêng `AFFILIATE_FB_APP_TOKEN_<PAGE_ID>`. Đặt `AFFILIATE_FB_GRAPH_VERSION` thành phiên bản Graph API ứng dụng đang dùng. Khởi động lại app rồi bấm **Kiểm tra kết nối** trong cài đặt Fanpage. Kết quả ghi nhận Page ID và quyền khai báo trong token. Lập lịch cục bộ, phát hành thật, bình luận và đồng bộ số liệu là các luồng riêng.

## Lập kế hoạch cảnh Reel

Tạo bản nháp, mở **Thêm cảnh Reel 9:16** rồi nhập prompt và thời lượng từng cảnh theo thứ tự. App hiển thị tổng thời lượng. Hãy kiểm tra kế hoạch trước khi duyệt bài. Tính năng này lưu kế hoạch cảnh, chưa gọi dịch vụ tạo video.

### Ví dụ bàn giao cho agent

Với Tủ Đồ Hay, xác nhận sản phẩm, ảnh gốc và link affiliate trước khi soạn cảnh. Khi mô tả cảnh, ghi hành động, góc máy và chi tiết phải giữ nguyên để video thể hiện đúng sản phẩm. Sau khi có clip, đối chiếu lại clip với ảnh gốc và link trước khi duyệt. Nếu thiếu ảnh gốc hoặc nhận ra sản phẩm sai, chuyển lại bước chọn sản phẩm.

## Nhập và ghép clip Reel

Cài FFmpeg và FFprobe rồi chạy app như bình thường. Trong bản nháp, nhập một MP4 dọc 9:16 cho mỗi cảnh. Dùng **Thay clip** để cập nhật clip của cảnh đó. Khi đủ clip, mở **Kiểm tra Reel**, chọn **Dựng bản xem trước** và phát video trên trang kiểm tra. Soát thứ tự, thời lượng, nội dung, sản phẩm và link affiliate rồi xác nhận kiểm tra trước khi duyệt bài. Khi sửa cảnh, đổi thứ tự hoặc thay clip, hãy dựng và kiểm tra lại.

Nút **Tải Reel MP4 không âm thanh** tải chính bản dựng đã xem khi có bản xem trước cho phiên bản hiện tại. Ghép âm thanh bên ngoài trước khi đăng nếu cần.

App lưu clip trong thư mục `media/` hoặc đường dẫn `AFFILIATE_MEDIA_DIR`. Chế độ này dùng tệp bạn cung cấp. Kết nối API tạo clip và đăng Facebook cần thực hiện riêng.
