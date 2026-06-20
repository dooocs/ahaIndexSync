-- ============================================================
-- Subject two-stage pipeline seed
--
-- Stage A: processed/display items -> subject_mentions
-- Stage B: subject_mentions -> subject_insights
-- ============================================================

INSERT INTO pipeline_params (key, value, description) VALUES
('subject_match_enabled', 'true', 'Subject Stage A catalog matcher switch; links processed items to existing visible subjects only'),
('subject_match_min_confidence', '0.65', 'Minimum confidence for catalog subject matching'),
('subject_match_max_subjects', '500', 'Maximum visible subjects loaded by the catalog matcher'),
('subject_insights_enabled', 'true', 'Subject Stage B read-model writer switch'),
('subject_insights_window_days', '14', 'Recent mention window used to generate subject insights'),
('subject_insights_max_subjects', '50', 'Maximum visible subjects processed by one insights run'),
('subject_insights_max_items_per_subject', '12', 'Maximum evidence items passed into one subject synthesis'),
('subject_insights_use_llm', 'false', 'When true, use the subject_insights_generate prompt for highlight/comparison synthesis; rule output remains the fallback')
ON CONFLICT (key) DO NOTHING;


INSERT INTO prompt_templates (name, stage, template, model, temperature, max_retries, request_interval) VALUES
('subject_insights_generate', 'subject_insights', E'你是 AmazingIndex 的 Subject 研究员。你的任务是把同一个 subject 最近关联到的内容重新梳理成可发布的主题观察，而不是复述单条新闻。\n\n快照日期：{snapshot_date}\n\nSubject:\n{subject_json}\n\nEvidence items（只能引用这里的 index）：\n{evidence_json}\n\nRelated subjects（comparison 只能引用这里的 subject_id 或 display_name）：\n{related_subjects_json}\n\n请只输出 JSON，结构如下：\n{\n  "highlight": {\n    "title": "不超过 30 个中文字符",\n    "summary": "80-160 字，概括这个 subject 当前最值得关注的变化",\n    "analysis": "120-260 字，说明为什么重要、对 AI 从业者意味着什么、后续要观察什么",\n    "event_date": "YYYY-MM-DD，可省略",\n    "importance_score": 0.0,\n    "evidence_indexes": [1]\n  },\n  "comparisons": [\n    {\n      "comparison_subject_ids": ["related subject id"],\n      "title": "不超过 30 个中文字符",\n      "summary": "60-140 字，说明共现或竞争关系",\n      "analysis": "100-220 字，说明这种关系的含义",\n      "event_date": "YYYY-MM-DD，可省略",\n      "importance_score": 0.0,\n      "evidence_indexes": [1]\n    }\n  ]\n}\n\n硬性要求：\n1. evidence_indexes 必须来自 Evidence items 里的 index，不能为空；没有证据就不要输出对应模块。\n2. comparison_subject_ids 只能使用 Related subjects 中已有的 subject_id；没有 related subject 就输出空数组。\n3. 不要编造未出现在 evidence 中的公司、产品、融资、发布时间、性能数字或结论。\n4. highlight 只输出 1 个；comparisons 最多 2 个。\n5. importance_score 使用 0-1 小数，越值得放在页面前面越高。\n6. 不要输出 Markdown，不要输出 JSON 以外的解释。', 'kimi-k2.6', 0.6, 2, 0.5)
ON CONFLICT (name) DO NOTHING;
