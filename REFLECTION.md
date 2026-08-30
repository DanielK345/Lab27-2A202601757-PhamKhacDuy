# Reflection

## Câu 1 — Chọn vị trí interrupt

Nên dùng `interrupt_after` trên node generate email. Con người cần nhận được bản
email đã sinh để rewrite, nhưng việc review phải xảy ra trước routing node kế
tiếp. Nếu dùng `interrupt_before` trên node generate thì UI chưa có nội dung để
sửa. Một cách diễn đạt tương đương là đặt `interrupt_before` trên routing node;
tuy nhiên `interrupt_after` node generate mô tả đúng ranh giới nghiệp vụ hơn.

## Câu 2 — Giảm alert fatigue

Không nên chỉ hạ threshold để làm biến mất cảnh báo. Trước mắt, UI nên gom các
email low-risk giống nhau thành batch, sắp xếp theo mức bất định/giá trị khách
hàng, cho phép approve theo batch và chỉ đẩy thông báo tức thời cho nhóm quan
trọng. Về architecture, thêm một vùng `0.80–0.85` cho phép auto-execute với mẫu
email đã duyệt, giới hạn nội dung và sampling ngẫu nhiên để hậu kiểm; các action
tài chính vẫn giữ hard rule. Theo dõi tỷ lệ override, lỗi và tải review để điều
chỉnh vùng này có kiểm soát.

## Câu 3 — Calibrate confidence

Confidence tự báo của LLM không phải xác suất đã được hiệu chuẩn. Mô hình có thể
rất tự tin khi dữ liệu TOI thiếu, cũ, sai đơn vị hoặc bị suy diễn; dùng trực tiếp
sẽ tạo cảm giác an toàn giả và cho quyết định tài chính sai đi qua routing.

Trước routing, cần kiểm tra TOI bằng nguồn dữ liệu có thẩm quyền và validation
schema/range/freshness. Sau đó đánh giá dự đoán trên tập holdout có nhãn, vẽ
reliability curve và đo Brier score/ECE; học bộ hiệu chuẩn như Platt scaling hoặc
isotonic regression để biến raw score thành xác suất thực nghiệm. Có thể kết hợp
độ đầy đủ/chất lượng dữ liệu, agreement giữa nhiều lần chạy và out-of-distribution
checks. Cuối cùng chọn threshold theo chi phí false positive/false negative và
giữ hard policy độc lập với confidence đã calibrate.
