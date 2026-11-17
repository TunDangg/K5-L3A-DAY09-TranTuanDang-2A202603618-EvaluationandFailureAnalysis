# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID: `seeded_regression-C-002-11` |
| Triệu chứng | Grader Lab 8 fail (`status resolved != denied`); ledger ghi `refund_vnd=20000` (nhãn = 0); reply thông báo đã hoàn 20.000đ |
| Bước sai đầu tiên | Event 3: kind `model_override`, payload `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 (`handoff`) và Event 2 (`investigator`) thực hiện đúng: DB trả về đơn hàng giao trễ 2 ngày (chưa đủ điều kiện hoàn). Event 3 tin ticket và đè giá trị thành 5 ngày |
| Failure mode | `FM-03` (ticket_trust — tin ticket hơn DB) |
| Đối chứng | Cùng claim@seed trên shape `fixed`: Không có event `model_override`; Event 3 chuyển thẳng sang `quote` với `amount_vnd=0`, đơn bị `denied`, ledger hoàn 0đ |
| Regression test | `test_override_event_breaks_db_fact` trong `tests/test_lab9_graders.py` (grader `DbFactKept`); kiểm tra fail trên `seeded_regression` và pass trên `fixed` |
| Chưa chắc chắn | Trace không hiển thị prompt nội bộ xem LLM có phát hiện sự mâu thuẫn giữa DB và ticket không, chỉ thấy kết quả cuối cùng là ghi nhận event override |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
