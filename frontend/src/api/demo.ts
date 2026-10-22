import type { AttackPathDetail } from './attackPaths'
import type { ChatMessage, MonitorSnapshot, ResourceUsage, RuntimeLog } from './monitor'
import type { ReportData } from './reports'
import type { VulnerabilityDetail } from './vulnerabilities'
import type { SandboxList, SystemLogList, SystemResourceSummary } from './admin'

export const DEMO_PROJECT_ID = 1
export const DEMO_RUN_ID = 2

const now = '2026-10-21T10:18:36+08:00'

export const DEMO_VULNERABILITIES: VulnerabilityDetail[] = [
  {
    id: 1,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 2,
    vuln_code: 'VULN-001',
    vuln_title: '硬编码数据库凭据',
    risk_level: 'critical',
    cvss_score: '8.8',
    file_path: 'src/main/resources/application.yml:42',
    verify_status: 'verified',
    impact_text:
      '应用配置文件中明文保存数据库账号与密码。攻击者获得源码或配置文件读取权限后，可直接连接生产数据库，读取订单、用户与支付相关数据。',
    condition_text:
      '攻击者能够读取 application.yml，或通过其他漏洞（如路径穿越）获取该文件内容。',
    evidence_text:
      'application.yml:42\nspring:\n  datasource:\n    username: shop_app\n    password: Shop@2026!',
    reproduce_steps_text:
      '1. 读取 src/main/resources/application.yml。\n2. 提取 datasource 用户名与密码。\n3. 使用数据库客户端连接并执行 SELECT 查询。',
    verify_code_text:
      'mysql -h db.internal -u shop_app -p' + '\n' + 'SHOW DATABASES;',
    created_at: now,
    updated_at: now,
  },
  {
    id: 2,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 2,
    vuln_code: 'VULN-002',
    vuln_title: '订单查询接口 SQL 注入',
    risk_level: 'critical',
    cvss_score: '9.1',
    file_path: 'src/main/java/com/example/order/OrderMapper.java:118',
    verify_status: 'unverified',
    impact_text:
      '攻击者可在 orderId 参数中注入任意 SQL，绕过查询条件读取订单、用户与支付记录；结合数据库权限可进一步写入数据。',
    condition_text:
      '普通用户访问 /api/orders/{id}，orderId 未做参数化处理，直接被拼接进 SQL 查询。',
    evidence_text:
      'GET /api/orders/1%20OR%201=1-- HTTP/1.1\nHost: shop.example.com\nCookie: session=****\n\nHTTP/1.1 200 OK\n{"total":1284,"items":[...]}',
    reproduce_steps_text:
      '1. 以普通用户登录，获取有效会话 Cookie。\n2. 请求 /api/orders/1%20OR%201=1--，观察返回全量订单。\n3. 将 orderId 替换为 UNION SELECT 语句，读取用户表。',
    verify_code_text:
      'SELECT * FROM orders\nWHERE id = 1 OR 1=1 --;\n\n-- 预期返回全量订单记录',
    created_at: now,
    updated_at: now,
  },
  {
    id: 3,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 3,
    vuln_code: 'VULN-003',
    vuln_title: '文件下载接口路径穿越',
    risk_level: 'high',
    cvss_score: '7.5',
    file_path: 'src/main/java/com/example/file/FileController.java:67',
    verify_status: 'verified',
    impact_text:
      '攻击者可构造包含 ../ 的 path 参数读取容器内任意可读文件，包括配置文件、日志与密钥材料。',
    condition_text:
      'GET /api/files?path= 参数未规范化校验，直接拼接至基础目录后读取文件。',
    evidence_text:
      'GET /api/files?path=../../etc/passwd\n\nHTTP/1.1 200 OK\nroot:x:0:0:root:/root:/bin/bash',
    reproduce_steps_text:
      '1. 登录普通账号。\n2. 请求 /api/files?path=../../etc/passwd。\n3. 响应返回系统文件内容。',
    verify_code_text:
      'curl -b "session=****" \\\n  "https://shop.example.com/api/files?path=../../etc/passwd"',
    created_at: now,
    updated_at: now,
  },
  {
    id: 4,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 2,
    vuln_code: 'VULN-004',
    vuln_title: '调试接口未鉴权',
    risk_level: 'medium',
    cvss_score: '5.3',
    file_path: 'src/main/java/com/example/debug/DebugController.java:23',
    verify_status: 'pending',
    impact_text:
      '调试接口暴露运行时配置、环境变量与内部服务地址，可能为后续攻击提供信息。',
    condition_text:
      'DebugController 未配置鉴权注解，任意未登录用户可访问 /debug/env。',
    evidence_text:
      'GET /debug/env\n\nHTTP/1.1 200 OK\nDB_HOST=db.internal\nREDIS_HOST=cache.internal',
    reproduce_steps_text:
      '1. 不携带 Cookie 访问 /debug/env。\n2. 响应包含数据库与缓存地址。',
    verify_code_text: 'curl https://shop.example.com/debug/env',
    created_at: now,
    updated_at: now,
  },
  {
    id: 5,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 2,
    vuln_code: 'VULN-005',
    vuln_title: '依赖组件版本过旧',
    risk_level: 'low',
    cvss_score: '3.1',
    file_path: 'pom.xml:88',
    verify_status: 'verified',
    impact_text:
      '项目依赖的 log4j-core 版本存在已知安全问题，建议升级至受支持版本。',
    condition_text:
      '构建文件中 log4j-core 版本低于厂商安全版本。',
    evidence_text:
      '<dependency>\n  <groupId>org.apache.logging.log4j</groupId>\n  <artifactId>log4j-core</artifactId>\n  <version>2.14.1</version>\n</dependency>',
    reproduce_steps_text:
      '1. 读取 pom.xml。\n2. 对比依赖公告中的受影响版本范围。',
    verify_code_text: 'mvn dependency:tree | grep log4j-core',
    created_at: now,
    updated_at: now,
  },
  {
    id: 6,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 3,
    vuln_code: 'VULN-006',
    vuln_title: '日志输出敏感信息',
    risk_level: 'medium',
    cvss_score: '4.2',
    file_path: 'src/main/java/com/example/common/LogUtil.java:31',
    verify_status: 'false_positive',
    impact_text:
      '候选问题认为日志会输出完整手机号与身份证号；验证阶段确认日志已脱敏，判定为误报。',
    condition_text: '分析阶段基于日志格式化代码产生的候选判断。',
    evidence_text:
      'logger.info("user={} phone={}", userId, MaskUtil.phone(phone));\n\n// MaskUtil.phone 对中间四位做了掩码',
    reproduce_steps_text:
      '1. 阅读 LogUtil.java 与 MaskUtil.java。\n2. 触发登录日志，确认手机号已脱敏。',
    verify_code_text: 'grep -n "phone" src/main/java/com/example/common/LogUtil.java',
    created_at: now,
    updated_at: now,
  },
]

const summary = (item: VulnerabilityDetail) => ({
  id: item.id,
  project_id: item.project_id,
  run_id: item.run_id,
  stage_id: item.stage_id,
  vuln_code: item.vuln_code,
  vuln_title: item.vuln_title,
  risk_level: item.risk_level,
  cvss_score: item.cvss_score,
  file_path: item.file_path,
  verify_status: item.verify_status,
  created_at: item.created_at,
  updated_at: item.updated_at,
})

export const DEMO_VULNERABILITY_SUMMARIES = DEMO_VULNERABILITIES.map(summary)

export const DEMO_ATTACK_PATHS: AttackPathDetail[] = [
  {
    id: 1,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    path_code: 'PATH-001',
    path_title: '路径穿越读取配置导致数据库凭据泄露',
    path_summary:
      '利用文件下载接口的路径穿越能力读取 application.yml，进而获取数据库账号与明文密码。',
    final_impact_text: '攻击者可获取数据库读写权限，读取订单、用户与支付相关数据。',
    step_count: 2,
    vulns: [summary(DEMO_VULNERABILITIES[2]), summary(DEMO_VULNERABILITIES[0])],
    steps: [
      {
        step_order: 1,
        step_text:
          '利用文件下载接口的路径穿越读取配置：GET /api/files?path=../../etc/passwd 可读取任意文件，进一步读取 application.yml。',
        vuln: summary(DEMO_VULNERABILITIES[2]),
      },
      {
        step_order: 2,
        step_text:
          '从配置文件获取数据库账号与明文密码：application.yml:42 明文保存数据库凭据，攻击者可直接连接数据库。',
        vuln: summary(DEMO_VULNERABILITIES[0]),
      },
    ],
  },
  {
    id: 2,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    path_code: 'PATH-002',
    path_title: 'SQL 注入获取管理员会话并访问调试接口',
    path_summary:
      '通过订单查询接口 SQL 注入读取会话表，复用管理员会话访问未鉴权的调试接口并获取内部服务地址。',
    final_impact_text: '攻击者可获取管理员权限并进一步访问内部服务。',
    step_count: 3,
    vulns: [
      summary(DEMO_VULNERABILITIES[1]),
      summary(DEMO_VULNERABILITIES[3]),
      summary(DEMO_VULNERABILITIES[0]),
    ],
    steps: [
      {
        step_order: 1,
        step_text: '通过订单查询接口 SQL 注入读取管理员会话记录。',
        vuln: summary(DEMO_VULNERABILITIES[1]),
      },
      {
        step_order: 2,
        step_text: '复用管理员会话访问 /debug/env，获取数据库与缓存地址。',
        vuln: summary(DEMO_VULNERABILITIES[3]),
      },
      {
        step_order: 3,
        step_text: '结合配置文件中的数据库凭据，直接连接生产数据库。',
        vuln: summary(DEMO_VULNERABILITIES[0]),
      },
    ],
  },
]

export const DEMO_REPORT: ReportData = {
  report_id: 2,
  project_id: DEMO_PROJECT_ID,
  run_id: DEMO_RUN_ID,
  report_file_path: 'data/reports/1/report-run-2',
  created_at: now,
  report_markdown: '# 电商后台服务安全评估报告（第 2 轮）\n\n## 1. 项目概述\n…',
  report_html: `
<h1>电商后台服务安全评估报告（第 2 轮）</h1>
<p class="report-meta">生成时间 2026-10-21 10:18:36 · 源码 commit a1b2c3d9e8f7 · SHA-256 3f9a7c2e…b41d8c21e</p>

<h2>1. 项目概述</h2>
<p>项目名称：电商后台服务安全评估；源码来源：Git 仓库 git@git.example.com:web/shop-api.git；评估轮次：第 2 轮；起止时间：2026-10-21 09:30:12 — 10:18:36。</p>
<p>任务说明：重点检查订单与支付相关接口的鉴权、SQL 注入与文件读取风险，并尝试串联可利用的攻击路径。</p>

<h2>2. 执行过程</h2>
<table>
  <thead><tr><th>阶段</th><th>状态</th><th>耗时</th><th>说明</th></tr></thead>
  <tbody>
    <tr><td>环境检查</td><td>成功</td><td>00:01:42</td><td>源码可读，Java 17 / Spring Boot 3.2</td></tr>
    <tr><td>代码分析</td><td>成功</td><td>00:18:36</td><td>分析 128 个文件，产出 6 条候选漏洞</td></tr>
    <tr><td>漏洞验证</td><td>成功</td><td>00:46:12</td><td>确认 3 条漏洞，2 条误报/未验证</td></tr>
    <tr><td>报告生成</td><td>成功</td><td>00:02:04</td><td>生成 Markdown 与 HTML 报告</td></tr>
    <tr><td>收尾</td><td>成功</td><td>00:00:30</td><td>资源归档，隔离环境已销毁</td></tr>
  </tbody>
</table>

<h2>3. 漏洞汇总</h2>
<table>
  <thead><tr><th>风险等级</th><th>数量</th></tr></thead>
  <tbody>
    <tr><td>严重</td><td>2</td></tr>
    <tr><td>高危</td><td>1</td></tr>
    <tr><td>中危</td><td>2</td></tr>
    <tr><td>低危</td><td>1</td></tr>
  </tbody>
</table>
<h3>VULN-001 硬编码数据库凭据（严重 / 已验证）</h3>
<p>影响说明：application.yml 明文保存数据库凭据。触发条件：攻击者可读取配置文件。证据：src/main/resources/application.yml:42。复现步骤：读取配置、提取凭据、连接数据库。验证代码：mysql -h db.internal -u shop_app -p。</p>
<h3>VULN-002 订单查询接口 SQL 注入（严重 / 未验证）</h3>
<p>影响说明：orderId 直接拼接 SQL。触发条件：普通用户访问 /api/orders/{id}。证据：请求 1 OR 1=1 后返回全量订单。该节点含待人工复核。</p>
<h3>VULN-003 文件下载接口路径穿越（高危 / 已验证）</h3>
<p>影响说明：可读取容器内任意可读文件。证据：/api/files?path=../../etc/passwd 返回系统文件。</p>

<h2>4. 攻击路径</h2>
<table>
  <thead><tr><th>路径</th><th>步骤</th><th>最终影响</th></tr></thead>
  <tbody>
    <tr><td>PATH-001 路径穿越读取配置导致数据库凭据泄露</td><td>VULN-003 → VULN-001</td><td>获取数据库读写权限</td></tr>
    <tr><td>PATH-002 SQL 注入获取管理员会话并访问调试接口</td><td>VULN-002 → VULN-004 → VULN-001</td><td>获取管理员权限（含待复核节点）</td></tr>
  </tbody>
</table>

<h2>5. 风险结论</h2>
<blockquote>整体风险等级：严重。存在可直接获取数据库凭据的高危利用链，且部分漏洞尚未完成验证，建议立即修复并人工复核未验证节点。</blockquote>

<h2>6. 修复建议</h2>
<ol>
  <li><strong>P0</strong> 移除硬编码凭据并轮换数据库密码（VULN-001）。</li>
  <li><strong>P0</strong> 对文件下载路径做白名单与规范化校验（VULN-003）。</li>
  <li><strong>P1</strong> 订单查询使用参数化 SQL 并补充鉴权（VULN-002）。</li>
  <li><strong>P1</strong> 为调试接口增加鉴权或下线（VULN-004）。</li>
</ol>
`,
}

const stageRows = [
  {
    stage_id: 1,
    stage_name: 'environment_scan',
    stage_status: 'success',
    started_at: '2026-10-21T09:30:12+08:00',
    finished_at: '2026-10-21T09:31:54+08:00',
    error_message: null,
  },
  {
    stage_id: 2,
    stage_name: 'code_analysis',
    stage_status: 'success',
    started_at: '2026-10-21T09:31:54+08:00',
    finished_at: '2026-10-21T09:50:30+08:00',
    error_message: null,
  },
  {
    stage_id: 3,
    stage_name: 'vulnerability_verify',
    stage_status: 'running',
    started_at: '2026-10-21T09:50:30+08:00',
    finished_at: null,
    error_message: null,
  },
  {
    stage_id: 4,
    stage_name: 'report_generate',
    stage_status: 'pending',
    started_at: null,
    finished_at: null,
    error_message: null,
  },
  {
    stage_id: 5,
    stage_name: 'done',
    stage_status: 'pending',
    started_at: null,
    finished_at: null,
    error_message: null,
  },
]

const workers = [
  {
    id: 1,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 3,
    worker_role: 'orchestrator',
    task_content: '协调漏洞验证与攻击路径整理',
    task_status: 'running' as const,
    result_summary: null,
    error_message: null,
    retry_count: 0,
    started_at: '2026-10-21T09:50:30+08:00',
    finished_at: null,
  },
  {
    id: 2,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 1,
    worker_role: 'env_inspector',
    task_content: '检查源码可读性与语言栈',
    task_status: 'success' as const,
    result_summary: '源码可读，Java 17 / Spring Boot 3.2',
    error_message: null,
    retry_count: 0,
    started_at: '2026-10-21T09:30:12+08:00',
    finished_at: '2026-10-21T09:31:54+08:00',
  },
  {
    id: 3,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 2,
    worker_role: 'code_analyst',
    task_content: '逐文件分析并产出候选漏洞',
    task_status: 'success' as const,
    result_summary: '产出 6 条候选漏洞',
    error_message: null,
    retry_count: 0,
    started_at: '2026-10-21T09:31:54+08:00',
    finished_at: '2026-10-21T09:50:30+08:00',
  },
  {
    id: 4,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 3,
    worker_role: 'vuln_verifier',
    task_content: '验证候选漏洞并补全证据',
    task_status: 'running' as const,
    result_summary: null,
    error_message: null,
    retry_count: 0,
    started_at: '2026-10-21T09:50:30+08:00',
    finished_at: null,
  },
  {
    id: 5,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 4,
    worker_role: 'report_writer',
    task_content: '汇总漏洞与攻击路径生成报告',
    task_status: 'idle' as const,
    result_summary: null,
    error_message: null,
    retry_count: 0,
    started_at: null,
    finished_at: null,
  },
  {
    id: 6,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 1,
    worker_role: 'ops_assistant',
    task_content: '资源采样与日志归档',
    task_status: 'success' as const,
    result_summary: '资源采样正常，日志已归档',
    error_message: null,
    retry_count: 0,
    started_at: '2026-10-21T09:30:12+08:00',
    finished_at: '2026-10-21T09:31:54+08:00',
  },
]

const messages: ChatMessage[] = [
  {
    id: 1,
    worker_role: 'orchestrator',
    message_type: 'info',
    message_text: '推送 vulnerability_found：VULN-002 订单查询接口 SQL 注入已落库。',
    created_at: '2026-10-21T10:12:48+08:00',
  },
  {
    id: 2,
    worker_role: 'vuln_verifier',
    message_type: 'result',
    message_text: '已确认 VULN-001 硬编码数据库凭据，风险等级 critical，证据与验证代码已保存。',
    created_at: '2026-10-21T10:12:30+08:00',
  },
  {
    id: 3,
    worker_role: 'vuln_verifier',
    message_type: 'tool_call',
    message_text: '执行 /workspace/verify_vuln003.sh，命中路径穿越并读取到 /etc/passwd。',
    created_at: '2026-10-21T10:08:52+08:00',
  },
  {
    id: 4,
    worker_role: 'code_analyst',
    message_type: 'tool_call',
    message_text: 'search_source("FileController") → src/main/java/.../FileController.java:67',
    created_at: '2026-10-21T10:02:44+08:00',
  },
  {
    id: 5,
    worker_role: 'code_analyst',
    message_type: 'result',
    message_text: '完成 128 个文件分析，产出 6 条候选漏洞，已提交验证。',
    created_at: '2026-10-21T09:49:04+08:00',
  },
]

const logs: RuntimeLog[] = [
  {
    id: 1,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 3,
    worker_task_id: 4,
    log_level: 'info',
    log_content: 'stage=vulnerability_verify status=running elapsed=00:22:00',
    created_at: '2026-10-21T10:12:52+08:00',
  },
  {
    id: 2,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 3,
    worker_task_id: 4,
    log_level: 'info',
    log_content: 'event=vulnerability_found vuln_id=VULN-002 run_id=2',
    created_at: '2026-10-21T10:12:48+08:00',
  },
  {
    id: 3,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 3,
    worker_task_id: 4,
    log_level: 'warning',
    log_content: 'cvss_score=8.8 inferred, needs manual review',
    created_at: '2026-10-21T10:12:30+08:00',
  },
  {
    id: 4,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 3,
    worker_task_id: 4,
    log_level: 'info',
    log_content: 'exec /workspace/verify_vuln003.sh exit=0 duration=1.42s',
    created_at: '2026-10-21T10:08:52+08:00',
  },
  {
    id: 5,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 2,
    worker_task_id: 3,
    log_level: 'info',
    log_content: 'search_source pattern=FileController matches=3',
    created_at: '2026-10-21T10:02:44+08:00',
  },
  {
    id: 6,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 2,
    worker_task_id: 3,
    log_level: 'info',
    log_content: 'stage=code_analysis status=success duration=00:18:36',
    created_at: '2026-10-21T09:49:04+08:00',
  },
  {
    id: 7,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 2,
    worker_task_id: 3,
    log_level: 'warning',
    log_content: 'source file too large, truncated: VendorBundle.java',
    created_at: '2026-10-21T09:48:21+08:00',
  },
  {
    id: 8,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 1,
    worker_task_id: 2,
    log_level: 'info',
    log_content: 'stage=environment_scan status=success duration=00:01:42',
    created_at: '2026-10-21T09:32:02+08:00',
  },
  {
    id: 9,
    project_id: DEMO_PROJECT_ID,
    run_id: DEMO_RUN_ID,
    stage_id: 1,
    worker_task_id: 6,
    log_level: 'info',
    log_content: 'container started image=sec-eval-sandbox:latest network=none',
    created_at: '2026-10-21T09:30:18+08:00',
  },
]

export const DEMO_RESOURCES: ResourceUsage[] = Array.from({ length: 16 }, (_, index) => ({
  id: index + 1,
  cpu_usage: (42 + index * 1.3).toFixed(2),
  memory_usage: 1040 + index * 26,
  token_count: 96000 + index * 2160,
  recorded_at: `2026-10-21T10:${String(11 + Math.floor(index / 4)).padStart(2, '0')}:${String((index * 4) % 60).padStart(2, '0')}+08:00`,
}))

export const DEMO_MONITOR_SNAPSHOT: MonitorSnapshot = {
  project_status: 'running',
  current_run_id: DEMO_RUN_ID,
  stages: stageRows,
  workers,
  recent_messages: messages,
  recent_logs: logs,
  latest_resource: DEMO_RESOURCES[DEMO_RESOURCES.length - 1],
  vuln_counts: { critical: 2, high: 1, medium: 2, low: 1, info: 0 },
}

export const DEMO_SANDBOXES: SandboxList = {
  items: [
    {
      sandbox_id: 'sec-eval-01',
      project_id: 1,
      project_name: '电商后台服务安全评估',
      status: 'running',
      created_at: '2026-10-21T09:30:12+08:00',
    },
    {
      sandbox_id: 'sec-eval-02',
      project_id: 2,
      project_name: '支付网关源码审计',
      status: 'stopped',
      created_at: '2026-10-20T14:02:11+08:00',
    },
    {
      sandbox_id: 'sec-eval-03',
      project_id: 3,
      project_name: '内部运维平台评估',
      status: 'failed',
      created_at: '2026-10-19T10:15:00+08:00',
    },
  ],
  cleanup_pending: [
    {
      project_id: 3,
      project_name: '内部运维平台评估',
      cleanup_error: '远端工作区目录删除超时，请重试',
      updated_at: '2026-10-21T09:20:00+08:00',
    },
  ],
}

export const DEMO_SYSTEM_RESOURCES: SystemResourceSummary = {
  running_projects: 1,
  cpu_usage: 62,
  memory_usage: 1432,
  token_count: 128430,
  projects: [
    {
      project_id: 1,
      project_name: '电商后台服务安全评估',
      cpu_usage: 62,
      memory_usage: 1432,
      token_count: 128430,
    },
  ],
}

export const DEMO_SYSTEM_LOGS: SystemLogList = {
  total: 8,
  page: 1,
  page_size: 20,
  items: [
    {
      id: 1,
      log_level: 'info',
      log_content: 'project_started project_id=1 run_id=2',
      source: 'projects',
      created_at: '2026-10-21T09:30:12+08:00',
    },
    {
      id: 2,
      log_level: 'info',
      log_content: 'audit login username=admin ip=127.0.0.1',
      source: 'auth',
      created_at: '2026-10-21T09:28:44+08:00',
    },
    {
      id: 3,
      log_level: 'warning',
      log_content: 'sandbox_cleanup_pending project_id=3 error=timeout',
      source: 'sandbox',
      created_at: '2026-10-21T09:20:00+08:00',
    },
    {
      id: 4,
      log_level: 'info',
      log_content: 'config_updated keys=sandbox.cpu_limit,timeout.stage_seconds',
      source: 'config',
      created_at: '2026-10-21T09:12:09+08:00',
    },
    {
      id: 5,
      log_level: 'error',
      log_content: 'llm_probe failed: auth_ok=false model=deepseek-chat',
      source: 'llm',
      created_at: '2026-10-21T09:05:33+08:00',
    },
    {
      id: 6,
      log_level: 'info',
      log_content: 'user_created username=demo_user role=user',
      source: 'users',
      created_at: '2026-10-20T18:22:10+08:00',
    },
    {
      id: 7,
      log_level: 'info',
      log_content: 'system_init admin_user_id=1',
      source: 'system',
      created_at: '2026-10-20T18:20:00+08:00',
    },
    {
      id: 8,
      log_level: 'info',
      log_content: 'service_started version=0.1.0',
      source: 'system',
      created_at: '2026-10-20T18:19:55+08:00',
    },
  ],
}
