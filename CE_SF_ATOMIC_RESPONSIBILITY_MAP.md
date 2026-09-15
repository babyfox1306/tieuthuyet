# CE SF Atomic Responsibility Map

Phase: Architecture Recon Phase 0
Status: Recon + protocol only - no early implementation
Date: 2026-09-15
Scope: Concept ETL (Concept ETL/) + Story Factory (tieuthuyet/)
Principle: no blind retry; local AI chi la worker disposable, validator moi la phan quyet

0. Muc dich

File nay dinh nghia ranh gioi node tien thiet ke cho ca CE va SF, cung mot protocol khoa sat chung dung de chung minh tinh nguyen tu (atomicity) cua tung node truoc khi refactor thuc.

Phase 0 chi recon + protocol. Khong implement test, khong uu tien truoc ve phia CE.

1. Nguyen tac then chot

1.1 Protocol chung cho ca CE va SF

Moi node denhap Hanh cung mot dong cho:

artifact -> authority -> validation -> defect -> causal trace -> repair -> revalidation

Boc | Y nghia
artifact | output/input tai border node
authority | source of truth ma node phai nghe
validation | deterministic gate, khong phu thuoc LLM
defect | loi bang chung duoc to chuc, co path, co repair class
causal trace | defect trace duoc ve node/origin cu the
repair | chi node co quyen repair moi cham artifact
revalidation | repair phai pass deterministic gate moi duoc chap nhan

1.2 No blind retry

Retry chi duoc phep khi:
- co mechanism phat hien loi cu the,
- co hypothesis ve nguyen nhan,
- co gioi han attempt ro rang,
- moi attempt ghi raw call + outcome de audit.

Khong duoc retry mu quang vi llm failed lan nua.

1.3 Validator la authority, local AI la worker disposable

- Local LLM / router / model call: co the thay, co the fallback, co the reprove.
- Validator deterministic: la phan quyet cuoi cung truoc khi artifact duoc chap nhan.
- Provenance ghi ai goi + ai phan + bang chung nao - khong phai AI said PASS.
