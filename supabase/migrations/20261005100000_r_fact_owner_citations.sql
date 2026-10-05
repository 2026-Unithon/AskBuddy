-- W3 typed facts may originate from an owner answer without a file occurrence.
begin;
alter table r_answer_citations drop constraint r_citation_owner_is_raw;
alter table fact_owner_answer_links add constraint fact_owner_revision_origin_key
  unique (store_id, fact_revision_id, owner_answer_id);
alter table r_answer_citations add constraint r_citation_owner_fact_origin_fk
  foreign key (store_id, fact_revision_id, owner_answer_id)
  references fact_owner_answer_links(store_id, fact_revision_id, owner_answer_id)
  on delete restrict;
-- The existing RAW origin FK and one-origin/one-reference checks still apply.
-- W links/meta already RESTRICT owner_answers deletion. R retains answer rows;
-- diagnostics retention only removes execution metadata, never provenance.
commit;
