# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | ĐẠT (0.757 ≥ 0.6, 0.857 ≥ 0.8, 0.800 ≥ 0.7) | Dùng |
| helpful | 100 | 0.375 | 1.000 | 0.300 | KHÔNG ĐẠT (κ=0.375 < 0.6, R=0.300 < 0.7) | Loại |

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | H-008 | PASS | FAIL | Người đúng | Câu trả lời suồng sã: *"Em đã hoàn tiền cho anh rồi nha, anh check giúp em"*, vi phạm quy chuẩn giao tiếp chuyên nghiệp của CSKH. |
| 2 | H-017 | PASS | FAIL | Người đúng | Dùng từ ngữ thiếu trang trọng (*"Dạ, bạn ơi... rồi nha"*), judge bị lừa bởi thái độ tưởng như thân thiện nhưng thực tế không đúng tone doanh nghiệp. |
| 3 | H-029 | PASS | FAIL | Người đúng | Giọng điệu cộc lốc, mệnh lệnh (*"Dạ, vui lòng chờ... không cần nhắn thêm"*), gây ức chế cho khách hàng; người gán FAIL là hoàn toàn chính xác. |
| 4 | H-042 | FAIL | PASS | Người đúng | Reply chuẩn mực, lịch sự: *"Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ"*. Judge bắt bẻ nhầm (False Positive của judge), gán FAIL vô lý. |
| 5 | HL-016 | PASS | FAIL | Người đúng | Khách khiếu nại nhưng agent chỉ xin lỗi sáo rỗng (*"Dạ, LogiX thành thật xin lỗi..."*) mà không giải quyết vấn đề. Judge bị đánh lừa bởi độ lịch sự bề ngoài. |

## Kết luận
- **Tiêu chí bị loại và lý do**: Tiêu chí `helpful` bị loại khỏi CI Gate do chỉ số $\kappa = 0.375$ (dưới sàn 0.6) và Recall chỉ đạt $0.300$ (dưới sàn 0.7). Ma trận nhầm lẫn của `judge_helpful`:
  $$\text{Confusion Matrix} = \{\text{tp}: 9, \text{fp}: 0, \text{fn}: 21, \text{tn}: 70\}$$
  Judge bỏ sót tới $21/30$ trường hợp phản hồi vô ích (tỷ lệ False Negative lên tới 70%), chỉ vì câu trả lời chứa các cụm từ xin lỗi lịch sự bề ngoài. Dùng judge này làm gate sẽ khiến các phản hồi sáo rỗng lọt qua hàng loạt.
- **Hành động sửa rubric**: Bổ sung tiêu chuẩn đánh giá định lượng cho `helpful` trong rubric: (1) Phải giải quyết đúng nhu cầu cốt lõi (xác nhận đơn/tiền/chính sách); (2) Đưa ra mốc thời gian hoặc hướng dẫn hành động tiếp theo rõ ràng; (3) Cấm coi lời xin lỗi chung chung là phản hồi hữu ích.
- **Rủi ro còn lại**: Judge hiện tại mới chỉ được hiệu chuẩn trên tập replay công khai (100 dòng CSV); cần thu thập thêm tập nhãn người held-out độc lập trên các tương tác thật để tránh overfitting rubric.
