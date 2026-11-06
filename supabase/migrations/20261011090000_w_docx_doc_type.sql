-- Phase B — 문서 자료에 docx 를 받는다. check 제약만 넓힌다(가산).
alter table source_scan drop constraint if exists source_scan_doc_type_check;
alter table source_scan add constraint source_scan_doc_type_check
  check (doc_type in ('PDF', 'JPG', 'PNG', 'DOCX'));
