# AhaIndexSync 链路与 Subject 方案依赖梳理

更新时间：2026-06-20  
范围：`ahaIndexSync/` 当前工作区代码、SQL、GitHub Actions，以及 `ahaIndex2` 对项目热力数据的读取边界。  
状态说明：本次梳理基于当前未提交工作区快照；仓库里已有 `sql/002_seed_data.sql`、`stages/tweet_aggregate.py`、`sql/014_fix_tweet_digest_content.sql`、`tests/test_tweet_aggregate.py` 的本地改动/新增文件，本文按当前工作区现状描述，不把这些改动当作已合并事实。

## 1. 结论先行

当前 `ahaIndexSync` 是一条配置驱动的数据生产链路：

```text
Supabase 配置表
  -> scrape raw_items + items_content
  -> tweet digest 聚合
  -> fetch_content 全文补全
  -> process processed_items
  -> coarse_filter 候选过滤
  -> enrich item_enrichments + subjects + subject_mentions
  -> rank display_items
  -> archive daily/weekly/monthly
  -> aggregate_projects project_heatmap_data
  -> GitHub dispatch 触发 ahaIndex2 构建
```

`subject` 方案不是一条独立主链路，而是嵌在 Enrich 阶段内生成的资产层：

- `subjects` 保存跨 item 复用的被追踪对象。
- `subject_mentions` 保存某日某条 item 提及了某个 subject。
- `subject_aliases` 是人工合并 slug 的入口。
- `item_enrichments` 保存 HN 评论、GitHub 生态、Web Search、历史关联等结构化增厚数据，并为 subject 发现提供候选。

当前自动创建的 subject 范围基本只覆盖 `type='project'`，主要来自 GitHub repo 本体、HN 评论里识别出的 GitHub repo、GitHub ecosystem 识别出的竞品 repo。表结构虽然允许 `project/product/org/person/concept`，但后四类目前没有自动抽取链路，更多依赖人工 seed 或后续扩展。

`subject` 的主要下游有两个：

- Rank 阶段读取当天 item 的 subject 以及最近 90 天历史，用作 LLM 精排提示。
- `aggregate_projects.py` 读取 `subjects/subject_mentions/item_enrichments/display_items/processed_items/tracks`，写 `project_heatmap_data`，供 `ahaIndex2` 的 `/projects` 页面读取。

最需要注意的依赖缺口：

- `tracks` 表被 Sync 和前台直接读取，但 `ahaIndexSync/sql/` 内没有找到完整 DDL。
- `SubjectRegistry.record_mention()` 对 `subject_mentions` 做 upsert 后无条件给 `subjects.mention_count + 1`，重跑同一 mention 会导致计数虚高。
- `web_search` enricher 需要 `TAVILY_API_KEY`，但当前 `_pipeline.yml` 没有把这个 secret 注入运行环境。
- `project_heatmap_data` 与 `aggregate_projects.py` 没有 `_test` 后缀隔离，当前测试链路不会覆盖这层。
- subject 发现依赖粗排后的候选，低分/死链/重复 item 不会进入 subject 资产层。

## 2. 当前主链路

### 2.1 入口与配置加载

`main.py` 只是参数入口，真正编排在 `pipeline/runner.py`：

- `--mode` 决定运行模式，默认 `daily`。
- `--suffix` 控制表后缀，比如 `_test`。
- `--scraper` 可指定单个 scraper。
- `--date` 设置 `snapshot_date`，用于历史回补。

运行开始后，`load_config()` 从 Supabase 读取：

- `scraper_configs`
- `prompt_templates`
- `rank_group_configs`
- `tag_slot_configs`
- `pipeline_params`
- `display_metrics_configs`
- `content_fetch_rules`

这些配置在一次 pipeline run 内作为快照使用，并写入 `pipeline_runs.config_snapshot`。

### 2.2 Scrape：配置源 -> raw_items / items_content

`stages/scrape.py` 遍历 enabled `scraper_configs`，按 priority 排序，使用 `scrapers.registry.get_engine(scraper_type)` 实例化抓取器。

每条 `RawItem` 写入前会注入：

- `snapshot_date`
- `scraper_slug`
- `source_type`
- `content_type`
- `scraper_config_snapshot`

然后写：

- `raw_items`：元数据、URL、来源、指标、发布时间等。
- `items_content.raw_body`：scraper 抓到的正文或摘要。

`RawItem.id` 是 `md5(original_url)`。这意味着 `raw_items`、`items_content`、`processed_items`、`subject_mentions`、`display_items` 都围绕同一个 item id 串起来。

### 2.3 Tweet Aggregate：tweet -> tweet_digest

当前工作区版本的 `stages/tweet_aggregate.py` 在 scrape 后、fetch_content 前运行：

- 读取当天 `content_type='tweet'` 的 `raw_items`，并 join `items_content(raw_body)`。
- 汇总 likes、retweets、replies、views、tweet_count。
- 写一条 `content_type='tweet_digest'` 的 synthetic `RawItem`。
- 同步写 `items_content.raw_body`，避免后续 Process 阶段 join 不到正文。
- digest 写入成功后删除原始 tweet rows 和对应 `items_content` rows。

这条链路会影响 subject 方案的候选池：原始 tweet 被聚合后，subject 抽取看到的是 digest，而不是每条 tweet 的原子事实。当前 subject 自动发现并不从 tweet_digest 中抽取 project/product/org/person。

### 2.4 Fetch Content：items_content.enriched_body

`stages/fetch_content.py` 找出 `items_content.enriched_body is null` 且 `fetch_attempts < 3` 的条目，通过 raw_items join 拿 URL：

- 命中 skip domain 的 URL 跳过。
- 其他 URL 用 Jina Reader 补全文，写 `enriched_body` 和 `enriched_source='jina'`。
- 失败时写 `last_fetch_error` 并递增 `fetch_attempts`。

后续 Process 阶段会优先使用 `enriched_body`，失败时回退到 `raw_body`。

### 2.5 Process：raw/content -> processed_items

`stages/process.py` 读取 raw_items + items_content，并用 `process_main` / `process_system` prompt 生成：

- `processed_title`
- `summary`
- `tags`
- `keywords`
- `category`
- `aha_index`
- `expert_insight`

同时组装 `display_metrics`，把媒体资源上传 OSS 后写回 `extra.media_urls`，最终 upsert 到 `processed_items`。

这一步是 subject 方案的前置质量源：

- `aha_index` 决定是否进入 coarse_filter。
- `tags` 后续用于 `aggregate_projects.py` 的 subject -> track 匹配。
- `summary/processed_title` 会进入 subject mention context、rank prompt、project_heatmap summary。
- `extra` 中的 GitHub repo metadata 会影响 GitHub ecosystem enrichment。

### 2.6 Coarse Filter：processed_items -> Enrich candidates

`stages/coarse_filter.py` 当前只做排除，不做重打分：

- 按 URL 去重，保留 `aha_index` 更高的 item。
- 过滤 `aha_index < coarse_filter_min_aha`。
- 做链接可访问性检查，过滤死链。
- 按 `aha_index` 降序返回候选。

这是 subject 方案的第一个关键闸门：只有粗排后的 candidates 会进入 Enrich，因此低分、重复或死链 item 不会产生 subject mention。

### 2.7 Enrich：候选 -> item_enrichments / subjects / subject_mentions

`stages/enrich.py` 是 subject 资产的直接生产者：

1. 检查 `pipeline_params.enrich_enabled`。
2. 实例化 `enrichers.registry.list_enrichers()` 返回的 enricher。
3. 每个 enricher 先 `preload()`，再对每个候选 item 顺序执行。
4. 每个 enricher 独立捕获异常，整体有 `enrich_timeout`。
5. `EnrichmentResult` 批量 upsert 到 `item_enrichments`。
6. GitHub repo 本体登记 primary subject mention。
7. enricher 产出的 `SubjectCandidate` 登记 mentioned subject mention。

当前 enricher 顺序：

- `cross_reference`
- `hn_comments`
- `github_ecosystem`
- `web_search`

### 2.8 Rank：enrichment/subject history -> display_items

`stages/rank.py` 对 candidates 做精排。它会额外读取：

- 当天 `item_enrichments`，按 item 聚合为 enrichment hints。
- 当天 item 绑定的 subject。
- 对应 subject 最近 90 天 `subject_mentions` 历史。

然后把这些信息拼入 rank prompt，LLM 打分后写 `display_items`。选中的 display row 还会把部分 enrichment 数据塞回 `extra.enrichment`，供前台展示。

### 2.9 Archive + Project Heatmap

生产模式下，Rank 后继续跑：

- `stages/archive.py`：从 `display_items` 生成 `daily_archives`，并在周/月边界生成 `weekly_archives`、`monthly_archives`。
- `stages/aggregate_projects.py`：从 subject 图谱和 display/read-model 数据生成 `project_heatmap_data`。

`aggregate_projects.py` 是当前 subject 方案的服务层聚合器。它只处理 `subjects.type='project'`。

### 2.10 触发 ahaIndex2

GitHub Actions 的 `_pipeline.yml` 在非 test run 成功后，用 `GH_PAT` 调 GitHub repository dispatch，触发 `dooocs/ahaIndex2` 的 `pipeline-done` 事件。前台 `ahaIndex2` build-time 读取 Supabase 中的 `display_items`、`daily_archives`、`project_heatmap_data`、`tracks` 等数据生成静态站点。

## 3. Subject 资产模型

### 3.1 表结构

`sql/003_enrich_and_subject_tables.sql` 定义 4 张核心表：

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `item_enrichments` | item 的二层增厚数据 | `(item_id, snapshot_date, enrichment_type)` 唯一 |
| `subjects` | 被追踪对象 | `slug` 唯一 |
| `subject_mentions` | subject 与 item 的多对多关联 | `(subject_id, item_id, snapshot_date)` 唯一 |
| `subject_aliases` | 手工 slug 合并 | `from_slug` 唯一，指向 `to_subject_id` |

`sql/003_enrich_and_subject_tables_test.sql` 提供 `_test` 版本，供 `TABLE_SUFFIX=_test` 使用。

`subjects.slug` 当前实际主格式是：

```text
github:owner/repo
```

表注释允许未来扩展：

```text
project / product / org / person / concept
```

但当前自动创建逻辑默认 `auto_create_types=("project",)`，非 project 类型如果未预先存在，会返回 `None`，不会自动建。

### 3.2 SubjectRegistry 行为

`stages/subject.py` 的 `SubjectRegistry` 做四件事：

1. 初始化时加载 `subject_aliases`，建立 `from_slug -> to_subject_id` 映射。
2. `upsert_subject()` 先查缓存，再查 alias，再查 `subjects.slug`。
3. 如果不存在且 type 属于 `auto_create_types`，插入 `subjects`。
4. `record_mention()` upsert `subject_mentions`，然后更新 `subjects.mention_count` 和 `last_seen_at`。

这里有一个当前风险：`record_mention()` 即使 upsert 命中了已有 `(subject_id, item_id, snapshot_date)`，仍会把 `mention_count + 1`。因此同一天重跑 Enrich/Rank 前置流程时，`subject_mentions` 不会重复，但 `subjects.mention_count` 可能虚高。

### 3.3 Subject 生成路径

#### 路径 A：GitHub repo 本体 -> primary mention

`stages/enrich.py` 会对所有进入 Enrich 的 candidates 调 `_register_primary_subjects()`：

- 用 `primary_github_repo_for_item()` 判断 item 是否是 GitHub repo。
- slug 为 `github:owner/repo`。
- 写入 `subjects(type='project')`。
- 写入 `subject_mentions(role='primary')`。

判断 repo 的规则：

- 如果 `content_type == 'repo'`，优先从 `extra.repo_full_name` 或 `extra.full_name` 取。
- 否则从 `original_url` 解析 `github.com/owner/repo`。

这意味着 GitHub Trending、GitHub Search 产出的 repo 是当前 subject 的最稳定来源。

#### 路径 B：HN 评论提到的 GitHub repo -> mentioned

`enrichers/hn_comments.py` 对 `source_name == 'HackerNews'` 且 `raw_metrics.hn_id` 存在的 item 运行：

- 调 HN Algolia item API 获取评论树。
- 取 Top comments，调用 `enrich_hn_comments` prompt。
- LLM 输出 `alternative_repos`。
- 每个 `owner/repo` 转成 `SubjectCandidate(type='project', role='mentioned')`。

如果缺 `KIMI_API_KEY` 或缺 prompt，则只保存原始评论摘要，不产生 subject candidate。

#### 路径 C：GitHub ecosystem 竞品 -> mentioned

`enrichers/github_ecosystem.py` 对 `content_type == 'repo'` 且可解析 GitHub repo 的 item 运行：

- 读取 item.extra 中的 topics、stars、description、readme 摘要；缺失时调 GitHub API 补 metadata。
- 用 topics 调 GitHub Search API 找同赛道候选。
- 调 `enrich_github_ecosystem` prompt，输出 competitors、ecosystem_position、maturity、unique_value。
- competitors 里的 `owner/repo` 转成 `SubjectCandidate(type='project', role='mentioned')`。

这个路径依赖：

- `GH_MODELS_TOKEN`：用于 GitHub API。
- `KIMI_API_KEY`：用于 LLM 竞品判断。
- GitHub source item 的 repo URL、topics、description、README 信息质量。

#### 路径 D：Cross Reference 历史关联 -> enrichment only

`enrichers/cross_reference.py` 是纯 DB 查询：

- 对 GitHub repo item 构造 `github:owner/repo` slug。
- 查当前已存在的 `subjects`。
- 查最近 90 天 `subject_mentions`。
- 输出 historical_mentions、same_day_cross_refs、trend。

它不会创建新 subject，只能在已有 subject 之上增强历史上下文。

#### 路径 E：Web Search -> enrichment only

`enrichers/web_search.py` 对 `content_type in ('article', 'hf_papers')` 的 item 运行：

- 用 Tavily Search 找相关文章/讨论。
- 用 `enrich_web_search` prompt 提取 related_articles 和 key_discussions。

当前不会产出 `SubjectCandidate`。此外，`.env.example` 有 `TAVILY_API_KEY`，但 GitHub Actions `_pipeline.yml` 没有注入这个 env，所以生产 workflow 里这一步会跳过。

## 4. Project Heatmap 下游链路

`stages/aggregate_projects.py` 是 subject 方案最完整的下游消费者。

它读取：

- `tracks`：active 赛道定义。
- `subjects`：只取 `type='project'`。
- `subject_mentions`：所有历史 mention。
- `processed_items`：按 item_id 加载 tags。
- `display_items`：按 item_id 加载最新 aha_index。
- `item_enrichments`：读取 `enrichment_type='ecosystem'` 的 competitors。
- `project_heatmap_data`：读取已有 track assignments 和 related_data，用于缓存/更新。

它产出：

- `project_heatmap_data`：`subject x snapshot_date` 粒度的前台读模型。
- `related_data.related`：共现关系。
- `related_data.competitors`：ecosystem 竞品 + 同 track 共现竞品。

它的处理步骤：

1. 加载 active `tracks`。
2. 加载所有 project subjects 和 mentions。
3. 用 processed item tags 构建 `subject_tags_map`。
4. 用 LLM 把 subject 分配到 track；已有 `project_heatmap_data.track_id` 的 subject 会复用缓存。
5. 基于同一 item 提到多个 subject 计算共现矩阵。
6. 合并 GitHub ecosystem competitors。
7. 写今天的 `project_heatmap_data` rows。
8. 更新已有 rows 的 `related_data`。

这里有两个设计事实：

- `tracks` 是硬依赖，但 `ahaIndexSync/sql/` 当前没有完整 tracks DDL。
- track assignment 当前主要缓存/冗余在 `project_heatmap_data`，没有独立的 `subject_tracks` 或 `item_tracks` 可审计关系表。

## 5. 前台消费边界

`ahaIndex2/src/lib/data.ts` 读取：

- `project_heatmap_data`
- `tracks`

然后在 build-time 聚合成 `ProjectEntry`：

- 按 `subject_id` 分组。
- 用 `subject_slug/subject_name/subject_type` 生成项目身份。
- 从 rows 里构建 timeline、current score、peak score、delta。
- 从 `related_data` 取 related 和 competitors。

`ahaIndex2/src/pages/projects/index.astro` 读取 `getProjects()` 和 `getProjectDates()`，按 track/category 画项目热力矩阵。

因此，对前台 `/projects` 来说，`project_heatmap_data` 是事实读模型，`subjects/subject_mentions/item_enrichments` 是上游生产细节。前台不会直接 join subject 原始表。

## 6. Subject 方案依赖矩阵

### 6.1 数据表依赖

| 层 | 表 | 依赖性质 | 说明 |
| --- | --- | --- | --- |
| 配置 | `scraper_configs` | 必需 | 决定来源、slug、source_type、content_type、抓取参数 |
| 配置 | `prompt_templates` | 必需 | Process、Enrich、Rank、Archive 使用 |
| 配置 | `pipeline_params` | 必需 | 控制 enrich/coarse/rank 并发、阈值、超时 |
| 配置 | `rank_group_configs` | 必需 | Rank 选哪些来源、每组取多少 |
| 配置 | `tag_slot_configs` | 可选增强 | Rank 特殊标签保底 |
| 配置 | `display_metrics_configs` | 前台展示依赖 | Process 写 display_metrics |
| 配置 | `content_fetch_rules` | 内容质量依赖 | 全文抓取与正文拼接规则 |
| Ingest | `raw_items` | 必需 | item id、URL、来源、metrics、extra、snapshot_date |
| Content | `items_content` | 必需 | `raw_body/enriched_body` 是 Process 输入 |
| Silver | `processed_items` | 必需 | Enrich candidates、Rank candidates、subject tags 来源 |
| Enrich | `item_enrichments` | 必需 | Rank hints、Project Heatmap competitors |
| Subject | `subjects` | 必需 | subject 身份主表 |
| Subject | `subject_mentions` | 必需 | item-subject 证据和时间线 |
| Subject | `subject_aliases` | 可选但重要 | 人工合并 slug |
| Serving | `display_items` | 必需 | 前台日报、Project Heatmap 当前分数 |
| Serving | `daily_archives` | 生产链路依赖 | 日报归档 |
| Serving | `project_heatmap_data` | `/projects` 必需 | 项目热力矩阵读模型 |
| Taxonomy | `tracks` | Project Heatmap 必需 | 赛道定义；当前缺少 sync 内 DDL |
| Observability | `pipeline_runs` / `scraper_runs` | 运维必需 | 运行状态、配置快照、scraper 失败追踪 |

### 6.2 字段级依赖

| 字段/形状 | 来自 | 被谁依赖 | 风险 |
| --- | --- | --- | --- |
| `raw_items.id = md5(original_url)` | `RawItem.id` | 所有下游 item join | URL 变体会产生不同 item |
| `snapshot_date` | runner 注入/override | 每日链路、subject_mentions、rank、heatmap | 需要回补时统一传 `--date` |
| `scraper_slug` | `scraper_configs.slug` | raw_items FK/历史追溯 | 依赖 `sql/008` 迁移和历史回填 |
| `content_type='repo'` | scraper/config | primary subject、github_ecosystem | 配错会导致 repo 不进 subject |
| GitHub URL | scraper | `primary_github_repo_for_item()` | 非标准 URL 可能解析失败 |
| `extra.repo_full_name/full_name` | scraper | GitHub repo 识别优先路径 | 当前 GitHub Search/Trending 主要靠 URL 兜底 |
| `extra.topics` | GitHub scraper/API | ecosystem 搜索、track 匹配间接依赖 | topics 少会降低竞品识别质量 |
| `raw_metrics.hn_id` | HN scraper | HN comments enricher | 缺失则无法抓 HN 评论 |
| `processed_items.tags` | Process LLM | aggregate_projects track 匹配 | LLM tag 泛化会影响分类 |
| `processed_items.aha_index` | Process LLM | coarse_filter、mention score、rank fallback、heatmap score | 分数质量直接影响 subject 时间线 |
| `item_enrichments.data.competitors` | GitHub ecosystem | Project Heatmap competitors | LLM 输出 schema 不稳会影响 related_data |
| `subject_mentions.score` | Enrich 阶段写入 | Rank history、Heatmap timeline | 取的是当时 processed aha_index |
| `subjects.mention_count` | `record_mention()` 更新 | Heatmap、前台展示 | 当前可能因重跑虚高 |

### 6.3 Prompt 和参数依赖

必需 prompt：

- `process_system`
- `process_main`
- `rank_system`
- `rank_idea`
- `rank_scoring`
- `rank_candidate`

Enrich 相关 prompt：

- `enrich_hn_comments`
- `enrich_github_ecosystem`
- `enrich_web_search`

Archive prompt：

- `archive_monthly_summary`

关键 params：

- `scraper_timeout`
- `process_max_workers`
- `fetch_window_hours`
- `link_check_max_workers`
- `coarse_filter_min_aha`
- `enrich_enabled`
- `enrich_timeout`
- `enrich_max_workers`
- `rank_batch_size`

### 6.4 外部服务和 secret 依赖

| Secret / 服务 | 当前用途 | Workflow 是否注入 |
| --- | --- | --- |
| `SUPABASE_URL` | 读写所有 Supabase 表 | 是 |
| `SUPABASE_SERVICE_ROLE_KEY` | pipeline server-side DB 权限 | 是 |
| `KIMI_API_KEY` | Process、Enrich LLM、Rank、Aggregate Projects、Archive monthly | 是 |
| `GH_MODELS_TOKEN` | GitHub Search scraper、GitHub ecosystem、README/language 拉取 | 是 |
| `TWITTERAPI_IO_KEY` | TwitterAPI.io 抓推文 | 是 |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | 图片上传 OSS | 是 |
| `GH_PAT` | dispatch 触发 ahaIndex2 | 是，用于 curl step |
| `TAVILY_API_KEY` | Web Search enricher | `.env.example` 有，workflow 未注入 |
| `PRODUCTHUNT_TOKEN` | Product Hunt scraper | `.env.example` 有，workflow 未注入；仅启用 Product Hunt 时相关 |

## 7. 当前方案的关键风险

### 7.1 Subject 计数不幂等

`subject_mentions` 有唯一索引避免重复 mention row，但 `subjects.mention_count` 是应用层读取后 `+1`。同一天同一 item 重跑会使 mention_count 增长，但真实 mention row 数不变。

建议把 `subject_mentions` 作为事实表，`mention_count` 改为：

- DB RPC：仅 insert 成功时递增。
- 或定时从 `subject_mentions` 重算。
- 或去掉缓存字段，前台/聚合阶段按需聚合。

### 7.2 `tracks` 是隐式外部 schema

`aggregate_projects.py` 和 `ahaIndex2` 都读 `tracks`，但 sync 的 SQL 目录没有 `tracks` DDL。未来扩展 subject/topic 时，如果不补这个 schema，AI 或人工改动容易漏字段、RLS、seed、测试数据。

建议新增可执行 migration，至少定义：

- `id`
- `slug`
- `display_name`
- `display_name_en`
- `description`
- `group_name`
- `cover_color`
- `display_order`
- `status`
- `created_at/updated_at`

### 7.3 Track assignment 不可审计

当前 subject -> track 匹配主要复用 `project_heatmap_data.track_id` 缓存。这个读模型同时承载前台展示和分类缓存，难以回答：

- 某个 subject 为什么被分到这个 track？
- 是 LLM 分的、人工修正的、还是历史缓存？
- track 体系变化后哪些 subject 需要重算？

建议新增 `subject_tracks`：

```sql
subject_id uuid references subjects(id),
track_id uuid references tracks(id),
source text not null, -- llm / manual / rule
confidence real,
evidence jsonb,
created_at timestamptz,
updated_at timestamptz,
primary key (subject_id, track_id)
```

### 7.4 自动 subject 类型过窄

表结构支持 `product/org/person/concept`，但当前自动创建只开 `project`。这对 GitHub 项目热力矩阵足够，但对更大的 subject/topic 方案不够。

如果要支持专题页、机构/person/product 趋势，需要新增：

- 从 Process 输出中抽取 entity candidates。
- 或在 Enrich 阶段新增 `entity_extractor`。
- 或在 Admin 里提供 subject seed/merge 工作台。

### 7.5 Web Search 在生产 workflow 中实际不会运行

`web_search` 需要 `TAVILY_API_KEY`，但 `_pipeline.yml` 没有注入。当前结果是它会打印缺 key 并跳过，不影响主链路，但 `item_enrichments.web_context` 会缺失。

### 7.6 Project Heatmap 没有 test suffix

`run_aggregate_projects()` 硬编码生产表名，不接收 table suffix。测试 workflow 跑 `_test` 时不会触达这层；生产才会生成 `project_heatmap_data`。

建议至少增加一个小型 fixture/unit test，覆盖：

- subject -> track 匹配缓存。
- co-occurrence related_data。
- ecosystem competitors merge。
- `project_heatmap_data` row shape。

### 7.7 Subject 依赖粗排，可能漏掉低分但重要的长期主体

当前 subject 创建在 coarse_filter 后。低分 item 不会形成 subject mention，因此 subject 图谱更像“日报候选图谱”，不是“全量事实图谱”。这符合当前日报产品，但如果 subject 方案要承载长期情报库，需要重新决定：

- subject 发现是否应发生在 Process 后、Coarse Filter 前。
- 低分 item 是否只写 mention 不进 rank。
- mention 是否区分 `candidate_only` / `displayed` / `filtered`。

## 8. Subject 方案扩展建议

### 8.1 先明确 subject 方案的边界

建议把当前方案命名为 `Project Subject V1`：

- 自动 subject 类型：只支持 `project`。
- 自动来源：GitHub repo item、HN alternative repos、GitHub ecosystem competitors。
- 主要服务：Rank 历史提示、Project Heatmap、未来 topic pages 的项目维度。

如果目标是更广义的 subject/topic intelligence，需要定义 `Subject V2`：

- 支持 `project/product/org/person/concept`。
- 每个 mention 需要 provenance、confidence、evidence。
- subject 与 track/topic 的关系要独立可审计。
- topic 计算不能只依赖 `project_heatmap_data`，需要读取事实层和 subject 层。

### 8.2 补一层 subject detection provenance

当前 `subject_mentions.context` 只有 500 字文本，不足以审计来源。建议扩列或新增子表：

```sql
alter table subject_mentions
  add column detected_by text,
  add column confidence real,
  add column evidence jsonb;
```

示例：

```json
{
  "detected_by": "github_ecosystem",
  "evidence": {
    "source_item": "xxx",
    "llm_field": "competitors[0]",
    "comparison": "same agent memory category"
  }
}
```

### 8.3 把 subject 写入改成 DB 原子操作

建议把 `upsert subject + insert mention + update counters` 合成一个 RPC：

```text
record_subject_mention(
  p_slug,
  p_type,
  p_display_name,
  p_item_id,
  p_snapshot_date,
  p_role,
  p_source_name,
  p_score,
  p_context,
  p_metadata
)
```

RPC 内部用 `insert ... on conflict do nothing returning id` 判断 mention 是否新插入，只在新 mention 时更新计数。

### 8.4 给 Aggregate Projects 加独立 contract test

当前最容易被改坏的是 `related_data` JSON shape。建议固定一个小 fixture：

- 3 个 subjects。
- 4 条 mentions。
- 2 个 tracks。
- 1 条 ecosystem enrichment competitors。

断言：

- 写入 rows 数量。
- `score_100` 正确。
- 同 track 共现为 `kind='竞品'`。
- 跨 track/group 共现为 `生态/互通`。
- competitors 同时包含 enricher 和 co-occurrence 来源。

### 8.5 明确前台读模型契约

`ahaIndex2` 实际依赖的是 `ProjectHeatmapRow` 和 `TrackInfo`。建议在 Sync 文档或 SQL 中同步维护一份 contract：

- `project_heatmap_data.related_data.related[]`
- `project_heatmap_data.related_data.competitors[]`
- `tracks` 字段列表

否则 Sync 改 JSONB shape 时，Astro build 可能只在运行时暴露问题。

## 9. 推荐落地顺序

1. 修 `SubjectRegistry.record_mention()` 幂等性，并补测试。
2. 补 `tracks` DDL/seed 或明确它由哪个仓库/迁移管理。
3. 给 `aggregate_projects.py` 增加 suffix 或至少增加 fixture/unit test。
4. 决定是否把 subject detection 移到 coarse_filter 前；如果仍在粗排后，就在产品定义里明确“subject 是日报候选图谱，不是全量事实图谱”。
5. 为 `subject_mentions` 增加 provenance/confidence/evidence。
6. 如果要启用 Web Search，把 `TAVILY_API_KEY` 加入 `_pipeline.yml` env。
7. 再推进 `Subject V2` 或 topic pages，不要直接把更复杂的 topic 逻辑塞进 `project_heatmap_data`。

## 10. 代码证据索引

| 主题 | 文件 |
| --- | --- |
| Pipeline 编排 | `pipeline/runner.py` |
| 配置加载 | `pipeline/config_loader.py` |
| 主入口 | `main.py` |
| 表名后缀和 DB helper | `infra/db.py` |
| RawItem / ContentRecord | `infra/models.py` |
| Scrape | `stages/scrape.py` |
| Tweet digest | `stages/tweet_aggregate.py` |
| Fetch content | `stages/fetch_content.py` |
| Process | `stages/process.py` |
| Coarse filter | `stages/coarse_filter.py` |
| Enrich | `stages/enrich.py` |
| Subject registry | `stages/subject.py` |
| Rank | `stages/rank.py` |
| Archive | `stages/archive.py` |
| Project Heatmap | `stages/aggregate_projects.py` |
| Enricher 协议 | `enrichers/base.py` |
| Enricher 注册顺序 | `enrichers/registry.py` |
| GitHub repo 解析 | `enrichers/_utils.py` |
| Cross reference | `enrichers/cross_reference.py` |
| HN comments | `enrichers/hn_comments.py` |
| GitHub ecosystem | `enrichers/github_ecosystem.py` |
| Web search | `enrichers/web_search.py` |
| Subject/enrich 表 | `sql/003_enrich_and_subject_tables.sql` |
| Subject/enrich 测试表 | `sql/003_enrich_and_subject_tables_test.sql` |
| Enrich seed | `sql/004_enrich_seed.sql` |
| Project heatmap 表 | `sql/007_project_heatmap.sql` |
| scraper slug 迁移 | `sql/008_scraper_configs_add_slug_and_types.sql` |
| items_content 表 | `sql/009_create_items_content.sql` |
| raw_items snapshot 字段 | `sql/011_raw_items_add_snapshot_columns.sql` |
| workflow | `.github/workflows/_pipeline.yml`, `.github/workflows/daily.yml`, `.github/workflows/test.yml` |
| 前台 heatmap 读取 | `../ahaIndex2/src/lib/data.ts`, `../ahaIndex2/src/lib/types.ts`, `../ahaIndex2/src/pages/projects/index.astro` |
