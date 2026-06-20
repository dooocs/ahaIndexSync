-- ============================================================
-- AhaIndexSync Seed Data - 将现有硬编码配置迁移到 Supabase
-- ============================================================

-- ── 1. scraper_configs ──────────────────────────────────────

-- GitHub Trending
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('github_trending', 'GitHub Trending', 10, '{
    "source_type": "REPO",
    "content_type": "repo",
    "timeout": 15
}');

-- GitHub Search
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('github_search', 'GitHub Search', 20, '{
    "source_type": "REPO",
    "content_type": "repo",
    "queries": [
        {"q": "created:>={last_week} stars:>100 topic:ai", "label": "一周内 AI topic"},
        {"q": "created:>={last_week} stars:>100 topic:llm", "label": "一周内 LLM topic"},
        {"q": "created:>={last_week} stars:>100 LLM in:name,description", "label": "一周内 LLM 关键词"}
    ],
    "per_page": 30,
    "fetch_window_days": 7,
    "badge_patterns": ["shields.io","badgen.net","img.shields.io","badge","ci-badge","codecov.io","travis-ci","github.com/workflows","actions/workflows","hits.dwyl.com","visitor-badge","star-history.com"],
    "max_readme_images": 3
}');

-- HackerNews
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('hackernews', 'HackerNews', 30, '{
    "source_type": "NEWS",
    "content_type": "article",
    "new_n": 500,
    "min_score": 50,
    "cutoff_hours": 36,
    "fetch_workers": 5,
    "skip_domains": ["twitter.com", "x.com", "medium.com", "zhihu.com"]
}');

-- Twitter (twscrape)
INSERT INTO scraper_configs (scraper_type, name, enabled, priority, config) VALUES
('twitter_twscrape', 'X (Twitter)', true, 40, '{
    "source_type": "TWEET",
    "content_type": "tweet",
    "watch_accounts": ["karpathy","sama","anthropic","openai","demishassabis","ylecun","drjimfan","svpino"],
    "tracked_keywords": ["context engineering","context window","MCP","skill","agentic workflow","multi-agent","agent memory","tool use","function calling","computer use","prompt caching","KV cache","speculative decoding","fine-tuning","LoRA","RLHF","RAG","vector database","LangChain","LlamaIndex","DSPy","Claude","GPT-5","Gemini","Llama","Mistral","DeepSeek"],
    "search_limit": 20,
    "timeline_limit": 5,
    "timeline_min_faves": 50,
    "max_age_days": 2
}');

-- RSS Feeds - AI 官方博客
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('rss', 'OpenAI Blog', 50, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://openai.com/news/rss.xml",
    "max_items": 10,
    "source_tag": "official_ai",
    "fetch_window_hours": 25
}'),
('rss', 'Google DeepMind Blog', 50, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://deepmind.google/blog/rss.xml",
    "max_items": 5,
    "source_tag": "official_ai",
    "fetch_window_hours": 25
}');

-- RSS Feeds - 科技媒体
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('rss', '36氪', 60, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://36kr.com/feed",
    "max_items": 3,
    "source_tag": "tech_media",
    "fetch_window_hours": 25
}'),
('rss', '虎嗅', 60, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://www.huxiu.com/rss/0.xml",
    "max_items": 2,
    "source_tag": "tech_media",
    "fetch_window_hours": 25
}'),
('rss', '奇客Solidot', 60, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://www.solidot.org/index.rss",
    "max_items": 3,
    "source_tag": "tech_media",
    "fetch_window_hours": 25
}'),
('rss', 'IT之家', 60, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://www.ithome.com/rss/",
    "max_items": 2,
    "source_tag": "tech_media",
    "fetch_window_hours": 25
}');

-- RSS Feeds - 消费科技
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('rss', '少数派', 60, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://sspai.com/feed",
    "max_items": 1,
    "source_tag": "consumer_tech",
    "fetch_window_hours": 25
}');

-- RSS Feeds - AI 研究/学术
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('rss', 'Huggingface Daily Papers', 55, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://raw.githubusercontent.com/huangboming/huggingface-daily-paper-feed/refs/heads/main/feed.xml",
    "max_items": 5,
    "source_tag": "ai_research",
    "fetch_window_hours": 25
}');

-- RSS Feeds - 工程领域
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('rss', 'CNCF Blog', 70, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://www.cncf.io/feed/",
    "max_items": 2,
    "source_tag": "engineering",
    "fetch_window_hours": 25
}'),
('rss', 'Chrome Developers Blog', 70, '{
    "source_type": "ARTICLE",
    "content_type": "article",
    "url": "https://developer.chrome.com/static/blog/feed.xml",
    "max_items": 2,
    "source_tag": "engineering",
    "fetch_window_hours": 25
}');

-- Twitter (Nitter RSS) - 默认禁用，公共实例不稳定
INSERT INTO scraper_configs (scraper_type, name, enabled, priority, config) VALUES
('twitter_nitter', 'Twitter @elonmusk', false, 80, '{
    "source_type": "TWEET",
    "content_type": "tweet",
    "twitter_user": "elonmusk",
    "source_tag": "social",
    "aggregate": true,
    "nitter_instances": ["https://nitter.poast.org"],
    "fetch_window_hours": 25
}'),
('twitter_nitter', 'Twitter @sama', false, 80, '{
    "source_type": "TWEET",
    "content_type": "tweet",
    "twitter_user": "sama",
    "source_tag": "social",
    "aggregate": true,
    "nitter_instances": ["https://nitter.poast.org"],
    "fetch_window_hours": 25
}'),
('twitter_nitter', 'Twitter @ylecun', false, 80, '{
    "source_type": "TWEET",
    "content_type": "tweet",
    "twitter_user": "ylecun",
    "source_tag": "social",
    "aggregate": true,
    "nitter_instances": ["https://nitter.poast.org"],
    "fetch_window_hours": 25
}'),
('twitter_nitter', 'Twitter @OpenAI', false, 80, '{
    "source_type": "TWEET",
    "content_type": "tweet",
    "twitter_user": "OpenAI",
    "source_tag": "official_ai",
    "aggregate": true,
    "nitter_instances": ["https://nitter.poast.org"],
    "fetch_window_hours": 25
}'),
('twitter_nitter', 'Twitter @AnthropicAI', false, 80, '{
    "source_type": "TWEET",
    "content_type": "tweet",
    "twitter_user": "AnthropicAI",
    "source_tag": "official_ai",
    "aggregate": true,
    "nitter_instances": ["https://nitter.poast.org"],
    "fetch_window_hours": 25
}'),
('twitter_nitter', 'Twitter @GoogleDeepMind', false, 80, '{
    "source_type": "TWEET",
    "content_type": "tweet",
    "twitter_user": "GoogleDeepMind",
    "source_tag": "official_ai",
    "aggregate": true,
    "nitter_instances": ["https://nitter.poast.org"],
    "fetch_window_hours": 25
}'),
('twitter_nitter', 'Twitter @karpathy', false, 80, '{
    "source_type": "TWEET",
    "content_type": "tweet",
    "twitter_user": "karpathy",
    "source_tag": "ai_research",
    "aggregate": true,
    "nitter_instances": ["https://nitter.poast.org"],
    "fetch_window_hours": 25
}'),
('twitter_nitter', 'Twitter @drjimfan', false, 80, '{
    "source_type": "TWEET",
    "content_type": "tweet",
    "twitter_user": "drjimfan",
    "source_tag": "ai_research",
    "aggregate": true,
    "nitter_instances": ["https://nitter.poast.org"],
    "fetch_window_hours": 25
}');

-- AI Blog scrapers (HTML 抓取)
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('ai_blog', 'Anthropic Blog', 15, '{
    "source_type": "BLOG",
    "content_type": "article",
    "base_url": "https://www.anthropic.com",
    "news_url": "https://www.anthropic.com/news",
    "link_selector": "a[href^=''/news/'']",
    "author": "Anthropic",
    "source_tag": "official_ai",
    "fetch_window_hours": 25
}'),
('ai_blog', 'Cohere Blog', 15, '{
    "source_type": "BLOG",
    "content_type": "article",
    "base_url": "https://cohere.com",
    "news_url": "https://cohere.com/blog",
    "link_selector": "a[href*=''/blog/'']",
    "author": "Cohere",
    "source_tag": "official_ai"
}'),
('ai_blog', 'Mistral AI Blog', 15, '{
    "source_type": "BLOG",
    "content_type": "article",
    "base_url": "https://mistral.ai",
    "news_url": "https://mistral.ai/news",
    "link_selector": "a[href*=''/news/'']",
    "author": "Mistral AI",
    "source_tag": "official_ai"
}'),
('ai_blog', 'Stability AI Blog', 15, '{
    "source_type": "BLOG",
    "content_type": "article",
    "base_url": "https://stability.ai",
    "news_url": "https://stability.ai/news",
    "link_selector": "a[href*=''/news/'']",
    "author": "Stability AI",
    "source_tag": "official_ai"
}');

-- Community scrapers
INSERT INTO scraper_configs (scraper_type, name, priority, config) VALUES
('community_v2ex', 'V2EX', 90, '{
    "source_type": "ARTICLE",
    "content_type": "v2ex_hot",
    "top_n": 10,
    "max_replies_to_fetch": 30,
    "max_replies_to_keep": 15,
    "source_tag": "dev_community"
}'),
('community_linuxdo', 'LINUX DO', 90, '{
    "source_type": "ARTICLE",
    "content_type": "linuxdo_hot",
    "top_n": 10,
    "max_replies_to_fetch": 30,
    "source_tag": "dev_community"
}');

-- ── 2. rank_group_configs ───────────────────────────────────

INSERT INTO rank_group_configs (group_name, source_names, "limit", must_include, sort_order) VALUES
('官方动态',  ARRAY['Anthropic Blog','OpenAI Blog','Mistral AI Blog','xAI Blog','Cohere Blog','Stability AI Blog'], 5, true, 10),
('开源项目',  ARRAY['GitHub Trending','GitHub Search'], 10, false, 20),
('技术社区',  ARRAY['HackerNews'], 10, false, 30),
('社交热点',  ARRAY['X (Twitter)','Twitter @anthropic','Twitter @openai','Twitter @GoogleDeepMind','Twitter @MetaAI','Twitter @MistralAI','Twitter @xai','Twitter @huggingface','Twitter @nvidia','Twitter @sama','Twitter @karpathy','Twitter @ylecun','Twitter @demishassabis','Twitter @GaryMarcus','Twitter @emollick','Twitter @drjimfan','Twitter @bindureddy','Twitter @ilyasut','Twitter @svpino','Twitter @hardmaru','Twitter @fchollet','Twitter @jeremyphoward','Twitter @alexalbert__','Twitter @swyx','Twitter @kaifulee','Twitter @drfeifei'], 5, false, 40),
('学术论文',  ARRAY['Huggingface Daily Papers'], 5, false, 50),
('工程动态',  ARRAY['CNCF Blog','Chrome Developers Blog'], 3, false, 60),
('平台动态',  ARRAY['Apple Developer News'], 2, true, 70),
('国内资讯',  ARRAY['虎嗅','奇客Solidot'], 1, false, 80),
('国内社区',  ARRAY['V2EX','LINUX DO'], 1, false, 90);

-- ── 3. tag_slot_configs ─────────────────────────────────────

INSERT INTO tag_slot_configs (tag_name, max_slots, min_score) VALUES
('gossip', 1, 45),
('deal', 1, 45),
('macro', 2, 45),
('incident', 1, 45),
('lifestyle', 1, 45);

-- ── 4. pipeline_params ──────────────────────────────────────

INSERT INTO pipeline_params (key, value, description) VALUES
('scraper_timeout', '120', '每个 scraper 的超时秒数'),
('process_max_workers', '3', 'AI 处理并发线程数'),
('link_check_max_workers', '10', '链接检查并发线程数'),
('fetch_window_hours', '24', 'raw_items 时间窗口（小时）');

-- ── 5. display_metrics_configs ──────────────────────────────

INSERT INTO display_metrics_configs (content_type, metrics) VALUES
('repo', '[{"label":"⭐ Stars","key":"stars","format":"number"},{"label":"📅 创建","key":"created_at","format":"days_ago"}]'),
('article', '[{"label":"📅 发布","key":"published_at","format":"date"}]'),
('tweet', '[{"label":"❤️ 点赞","key":"likes","format":"number"},{"label":"🔁 转发","key":"retweets","format":"number"},{"label":"💬 回复","key":"replies","format":"number"}]'),
('tweet_digest', '[{"label":"🐦 推文","key":"tweet_count","format":"number"},{"label":"❤️ 点赞","key":"likes","format":"number"},{"label":"🔁 转发","key":"retweets","format":"number"}]'),
('news', '[{"label":"▲ 热度","key":"score","format":"number"},{"label":"💬 评论","key":"comments","format":"number"}]');

-- ── 6. content_fetch_rules ──────────────────────────────────

-- skip domains
INSERT INTO content_fetch_rules (rule_type, value) VALUES
('skip_domain', 'twitter.com'),
('skip_domain', 'x.com'),
('skip_domain', 'medium.com'),
('skip_domain', 'zhihu.com'),
('skip_domain', 'v2ex.com');

-- fetch fulltext tags
INSERT INTO content_fetch_rules (rule_type, value) VALUES
('fetch_fulltext_tag', 'official_ai'),
('fetch_fulltext_tag', 'ai_research');

-- ── 7. prompt_templates ─────────────────────────────────────

-- Process prompt (AI 编辑处理)
INSERT INTO prompt_templates (name, stage, template, model, temperature, max_retries, request_interval) VALUES
('process_system', 'process', 'You only output JSON.', 'kimi-k2.5', 0.1, 3, 0.5),
('process_main', 'process', E'你是一个 AI 技术日报的资深编辑，风格参考 TLDR Newsletter：信息密度高、直击重点、让读者 5 秒内判断是否值得深读。\n\n读者是 AI 工程师和创业者，他们时间有限，需要你帮他们快速过滤噪音。\n\n待分析内容：\n来源: {source_name}\n来源类型: {source_tag}\n标题: {title}\n内容: {body_text}\n热度指标: {raw_metrics}\n\n请输出 JSON，字段要求如下：\n\nprocessed_title:\n  - 15字以内中文标题\n  - 突出"做了什么"或"解决了什么问题"，而不是复述原标题\n  - 好的例子："Meta 开源最强多模态模型 Llama 4"、"用 RAG 把幻觉率降低 60%"\n  - 坏的例子："关于大型语言模型的工具"、"AI 代理新框架介绍"\n\nsummary:\n  - 2句话，不超过100字\n  - 第1句：这是什么/做了什么（事实）\n  - 第2句：为什么值得关注/对读者有什么用（价值）\n  - 不要重复标题，不要说废话如"这是一个..."\n\ntags:\n  - 最多3个\n  - 优先写具体名称：产品名、技术名、框架名（如 LangChain、RAG、Llama）\n  - 禁止写泛泛标签：AI、机器学习、人工智能、开源（除非是核心卖点）\n\nkeywords: 英文技术关键词，2-5个\n\ncategory: 从以下选一个: tech / finance / entertainment / academic\n\naha_index:\n  - 0.0-1.0 浮点数\n  - 参考：大厂官方重大发布=0.85-0.95，热门开源新工具=0.65-0.80，普通资讯=0.40-0.60\n  - 热度指标（stars/score）高的可以适当加分\n\nexpert_insight:\n  - 这是编辑点评，是整条内容中最有价值的部分\n  - 严格要求：必须写出标题和摘要里没有的信息，禁止复述已有内容\n  - 纯文本，不使用 Markdown 格式（不要 ###、不要 **、不要列表符号 -）\n  - 总字数 80-150 字，2-3 个自然段落，段落之间用换行分隔\n\n  根据内容类型，侧重点不同：\n\n  如果是开源项目/工具：\n    写清楚三件事：这个工具解决的痛点之前大家怎么解决的、跟同类工具（指名道姓）比优势在哪、什么人/场景最该试试。\n    好的示例："做 RAG 的团队之前大多用 LangChain + Chroma 的组合，但检索精度一直是痛点。这个框架用混合检索（BM25 + 向量）把准确率拉到了 94%，而且不需要 GPU。\\n如果你的 RAG 管线还在用纯向量检索，值得花半小时跑一下它的 benchmark。"\n\n  如果是行业新闻/收购/融资：\n    写清楚三件事：背后的战略逻辑、对哪些公司/赛道构成直接威胁或利好、读者需要做什么（调整技术选型、关注新机会、规避风险）。\n    好的示例："OpenAI 收 Windsurf 不是为了编辑器本身，而是在补 AI 原生开发工具链这块短板。这意味着 Cursor、Bolt 这些独立 AI IDE 的窗口期在缩短。\\n如果你在做 AI 编程工具方向的创业，需要重新评估和 OpenAI 正面竞争的可能性。"\n\n  如果是论文/研究：\n    写清楚三件事：核心方法用一句大白话讲清楚（不要学术黑话）、比之前的 SOTA 好在哪好多少、工程落地的可能性（算力需求、有没有开源代码）。\n    好的示例："这篇论文的核心思路是让小模型在推理时自我纠错，不需要外部反馈。在 GSM8K 上把 7B 模型的推理准确率从 58% 拉到了 72%，逼近 GPT-4 早期水平。\\n代码已开源，如果你在做端侧推理，这个方法的性价比很高。"\n\n  如果是社交媒体/大佬观点：\n    写清楚三件事：这个人为什么在这个时间点说这句话、背后可能暗示什么行业信号、哪些人该特别关注。\n    好的示例："Karpathy 公开说 LLM 的下一个突破不在模型架构而在数据，这个时间点很微妙——正好是 Llama 4 因为训练数据问题被质疑之后。\\n做数据标注、数据清洗、合成数据赛道的团队可以重点关注，行业风向可能在转。"\n\n  如果是其他类型：\n    对 AI 从业者意味着什么？有什么可以立刻行动的建议？\n\n  坏的示例（禁止出现类似内容）：\n    "掌握CPU分支预测技术，提升算法效率。" → 这是废话，标题已经说了\n    "框架持续更新，新增模型支持，对金融交易领域AI应用有重要意义。" → 这是摘要的复述\n    "OpenAI 的此次收购可能带来 AI 技术的新突破。" → 这是任何人都能说的空话，没有具体判断', 'kimi-k2.5', 0.1, 3, 0.5);

-- Rank scoring system prompt
INSERT INTO prompt_templates (name, stage, template, model, temperature) VALUES
('rank_system', 'rank', 'You are a JSON-only scorer. Output valid JSON and nothing else.', 'kimi-k2.5', 0.1);

-- Rank idea guide
INSERT INTO prompt_templates (name, stage, template, model, temperature) VALUES
('rank_idea', 'rank', E'- 重大的更新\n  - 苹果的新闻稿：https://developer.apple.com/cn/news/\n- 薅羊毛、福利之类的，比如ChatGPT/Codex 6月Pro福利发放, 比如某些APP限免\n- 宕机类，大家对于宕机喜闻乐见\n- 公开的裁员信息，给大家敲醒\n- 公共开的收购信息，说明了行业的趋势\n- 发布了新的学习资源\n- 大宗商品的价格波动\n- 一些新的领域初创公司出现\n- 一些好的博客、好的APP、好的效率工具、好的电影、好的音乐、好的艺术的作品、好的游戏\n- 顶级人才的讯息\n- 八卦，大佬之间的八卦', 'kimi-k2.5', 0.1);

-- Rank scoring guide (the full scoring.md content)
INSERT INTO prompt_templates (name, stage, template, model, temperature) VALUES
('rank_scoring', 'rank', E'# AhaIndex 精排评分体系 v2\n\n你是一名资深 AI 行业从业者兼日报编辑，负责从候选内容中为 AI 从业者（工程师、产品经理、创始人、投资人）筛选每日最值得关注的内容。\n\n## 评分维度\n\n对每条候选内容，按以下 5 个正向维度打分，再评估 2 个扣分项。\n\n---\n\n### 1. 可行动性（actionability）：0-30 分\n\n> 核心问题：读完之后，读者的认知或行为是否会产生变化？\n\n| 分档 | 标准 | 举例 |\n|---|---|---|\n| 25-30 | 读完可以直接用，改变今天的工作方式 | 新开源工具附带教程、可直接调用的新 API、即学即用的 prompting 技巧 |\n| 15-24 | 影响近期的技术选型或产品方向 | 框架性能对比 benchmark、模型能力评测、行业最佳实践总结 |\n| 5-14 | 提供背景认知，但短期无法直接行动 | 行业趋势分析、远期技术路线讨论 |\n| 0-4 | 读完即忘，无行动指引 | 纯转述新闻、空洞观点、没有干货的圆桌对话 |\n\n### 2. 技术纵深（tech_depth）：0-25 分\n\n> 核心问题：内容是否有真正的技术含量？\n\n| 分档 | 标准 | 举例 |\n|---|---|---|\n| 20-25 | 有第一手技术成果且讲清楚了原理 | 带代码的工程实践、有实验数据的论文解读、架构设计拆解 |\n| 10-19 | 有技术细节但非原创，或原创但较浅 | 对他人论文的深度解读、带对比的工具评测 |\n| 1-9 | 涉及技术话题但缺乏实质细节 | \"XX 模型用了 MoE 架构\"一句话带过 |\n| 0 | 无技术内容 | 纯商业新闻、人事变动、融资通稿 |\n\n⚠️ **重要**：技术纵深 = 0 是正常的。新闻、行业动态、政策变化等非技术类内容在该维度拿 0 分不代表内容质量差，其他维度会补偿。\n\n### 3. 格局影响（impact）：0-20 分\n\n> 核心问题：这件事是否会改变行业竞争态势、技术路线或商业版图？\n\n| 分档 | 标准 | 举例 |\n|---|---|---|\n| 16-20 | 改变行业格局的重大事件 | 顶级模型发布、重大开源、颠覆性政策法规、关键并购 |\n| 8-15 | 影响某个细分领域的走向 | 细分赛道大额融资、重要人事变动、区域性政策 |\n| 1-7 | 有一定影响但范围有限 | 常规产品更新、中小规模合作 |\n| 0 | 对格局无影响 | 教程、工具推荐、个人观点文 |\n\n### 4. 事件稀缺性（scarcity）：0-15 分\n\n> 核心问题：这种事多久才发生一次？\n\n| 分档 | 标准 | 举例 |\n|---|---|---|\n| 12-15 | 全球范围内极少发生的事件 | GPT/Gemini/Claude 大版本发布、千亿级并购 |\n| 6-11 | 同类事件每月只发生几次 | 知名研究者跳槽、独角兽新一轮融资 |\n| 1-5 | 同类事件经常发生，但这次有些不同 | 常规融资但金额异常大 |\n| 0 | 高频重复事件 | 又一家公司投了某 AI 创业公司 |\n\n### 5. 受众匹配度（audience_fit）：0-10 分\n\n> 核心问题：AI 从业者会关心这件事吗？\n\n| 分档 | 标准 | 举例 |\n|---|---|---|\n| 8-10 | AI 从业者直接相关的核心话题 | AI 模型、框架、基础设施 |\n| 4-7 | 与 AI 从业者间接相关 | 芯片政策、云计算、开发者工具 |\n| 1-3 | 泛科技话题，与 AI 有弱关联 | 传统行业用了 AI |\n| 0 | 与 AI 从业者完全无关 | 非科技领域新闻 |\n\n---\n\n### 扣分项\n\n#### 营销浓度（marketing_penalty）：扣 0-15 分\n#### 重复度（duplicate_penalty）：扣 0-15 分\n#### 政治内容（political_penalty）：扣 0 或 30 分\n\n---\n\n### 特殊标签（tags）\n\n| 标签 | 定义 | 每日上限 |\n|---|---|---|\n| gossip | AI 圈八卦 | 1 条 |\n| deal | 优惠福利 | 1 条 |\n| macro | 跨界大事件 | 2 条 |\n| incident | 宕机/故障 | 1 条 |\n| lifestyle | 好物推荐 | 1 条 |\n\n## 总分计算\n\n总分 = 可行动性 + 技术纵深 + 格局影响 + 事件稀缺性 + 受众匹配度 - 营销浓度 - 重复度 - 政治内容\n范围：-60 ~ 100', 'kimi-k2.5', 0.1);

-- Rank candidate prompt template
INSERT INTO prompt_templates (name, stage, template, model, temperature) VALUES
('rank_candidate', 'rank', E'你是 AI 日报编辑，请对以下「{group}」的 {count} 条候选内容逐条打分。\n\n## 优先关注的内容方向\n{idea_guide}\n\n## 评分体系\n{scoring_guide}\n\n## 数据源说明\n参考指标（stars, score 等）仅作为辅助参考，不能直接决定分数。注意不同来源的指标含义不同：\n- GitHub Trending：当前热门项目，stars 通常较高，但高 star 不等于高质量\n- GitHub Search：最近 7 天新创建的项目，stars 通常很低，但可能代表未来方向，不要因为 star 低就给低分\n- HackerNews：score 反映社区热度，但热度不等于对 AI 从业者的价值\n- Twitter：tweet_count 是聚合推文数，关注内容本身而非数量\n- 其他来源：参考指标仅供了解上下文\n\n## 候选内容\n{candidate_text}\n\n请严格按照评分体系中的 5 个正向维度和 3 个扣分项打分，并判断是否需要标记特殊标签（gossip/deal/macro/incident/lifestyle）。\n\n输出 JSON（不要输出任何其他内容）：\n{{\n  \"scores\": [\n    {{\n      \"index\": 1,\n      \"actionability\": 0,\n      \"tech_depth\": 0,\n      \"impact\": 0,\n      \"scarcity\": 0,\n      \"audience_fit\": 0,\n      \"marketing_penalty\": 0,\n      \"duplicate_penalty\": 0,\n      \"political_penalty\": 0,\n      \"total\": 0,\n      \"tags\": [],\n      \"comment\": \"一句话理由\"\n    }}\n  ]\n}}', 'kimi-k2.5', 0.1);

-- Archive monthly summary prompt
INSERT INTO prompt_templates (name, stage, template, model, temperature, max_retries, request_interval) VALUES
('archive_monthly_summary', 'archive', E'你是 AmazingIndex 的编辑。根据以下本月每日 Top Story 标题列表，撰写一段 80-120 字的月度摘要。\n要求：\n1. 中文撰写，语气客观专业\n2. 提及本月 2-3 个最重要的事件/发布\n3. 点明行业趋势关键词\n4. 最后一句用数据收尾（如\"本月Aha Index均值{avg_score}，为近三个月最高\"）\n5. 不要使用 markdown 格式，直接输出纯文本\n\n月份：{year}年{month}月\nTop Story 列表：\n{top_stories}', 'kimi-k2.5', 0.1, 3, 0.5);
