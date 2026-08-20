# Horizon game-inspiration radar: dense publication-style technical route.
# Icon-led schematic rendered exclusively in R.

library(grid)

required_packages <- c("svglite", "ragg", "rsvg", "png")
missing_packages <- required_packages[
  !vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)
]
if (length(missing_packages)) {
  stop(
    "Missing R packages: ", paste(missing_packages, collapse = ", "),
    ". Install with install.packages(c('svglite', 'ragg', 'rsvg', 'png'))."
  )
}

out_dir <- file.path("docs", "figures", "generated")
icon_dir <- file.path("docs", "figures", "icons")
generated_icon_dir <- file.path("docs", "figures", "generated-icons")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
out_base <- file.path(out_dir, "game-inspiration-pipeline")

width_mm <- 183
height_mm <- 190
width_in <- width_mm / 25.4
height_in <- height_mm / 25.4

COL <- c(
  ink = "#20292E",
  muted = "#68777F",
  border = "#B7C3C8",
  light = "#F4F7F8",
  blue = "#2D607E",
  blue_pale = "#EAF2F6",
  teal = "#4F8781",
  teal_pale = "#EDF5F3",
  red = "#A44D47",
  red_pale = "#F8EEED",
  gold = "#A97835",
  gold_pale = "#F7F1E7",
  white = "#FFFFFF"
)

FONT <- if (.Platform$OS.type == "windows") "Microsoft YaHei" else "Arial"
icon_cache <- new.env(parent = emptyenv())
generated_cache <- new.env(parent = emptyenv())

gp_text <- function(size = 6, colour = COL[["ink"]], face = "plain") {
  gpar(fontfamily = FONT, fontsize = size, col = colour, fontface = face)
}

txt <- function(text, x, y, size = 6, colour = COL[["ink"]], face = "plain",
                just = "centre", rot = 0) {
  grid.text(text, x = unit(x, "npc"), y = unit(y, "npc"), just = just,
            rot = rot, gp = gp_text(size, colour, face))
}

rule <- function(x0, y0, x1, y1, colour = COL[["border"]], lwd = 0.55,
                 lty = 1) {
  grid.lines(x = unit(c(x0, x1), "npc"), y = unit(c(y0, y1), "npc"),
             gp = gpar(col = colour, lwd = lwd, lty = lty))
}

flow_arrow <- function(x0, y0, x1, y1, colour = COL[["ink"]], lwd = 0.75) {
  grid.lines(x = unit(c(x0, x1), "npc"), y = unit(c(y0, y1), "npc"),
             arrow = grid::arrow(type = "closed", length = unit(1.25, "mm")),
             gp = gpar(col = colour, lwd = lwd))
}

orth_arrow <- function(points, colour = COL[["ink"]], lwd = 0.65) {
  grid.lines(x = unit(vapply(points, function(point) point[[1]], numeric(1)), "npc"),
             y = unit(vapply(points, function(point) point[[2]], numeric(1)), "npc"),
             arrow = grid::arrow(type = "closed", length = unit(1.2, "mm")),
             gp = gpar(col = colour, lwd = lwd))
}

panel_box <- function(left, bottom, w, h, fill = COL[["white"]],
                      border = COL[["border"]], lwd = 0.6) {
  grid.roundrect(x = unit(left + w / 2, "npc"), y = unit(bottom + h / 2, "npc"),
                 width = unit(w, "npc"), height = unit(h, "npc"),
                 r = unit(1.4, "mm"), gp = gpar(fill = fill, col = border, lwd = lwd))
}

section_title <- function(label, title, x, y, colour = COL[["muted"]]) {
  txt(label, x, y, 6.3, COL[["ink"]], "bold", "left")
  txt(title, x + 0.018, y, 5.8, colour, "bold", "left")
}

sub_title <- function(label, title, left, top, colour = COL[["ink"]]) {
  txt(label, left + 0.012, top - 0.018, 5.0, colour, "bold", "left")
  txt(title, left + 0.040, top - 0.018, 5.0, COL[["muted"]], "bold", "left")
}

load_icon <- function(name, colour, px = 384) {
  key <- paste(name, colour, px, sep = "|")
  if (exists(key, envir = icon_cache, inherits = FALSE)) {
    return(get(key, envir = icon_cache, inherits = FALSE))
  }
  path <- file.path(icon_dir, paste0(name, ".svg"))
  if (!file.exists(path)) stop("Missing icon asset: ", path)
  svg <- paste(readLines(path, warn = FALSE), collapse = "")
  svg <- gsub("currentColor", colour, svg, fixed = TRUE)
  rendered <- rsvg::rsvg_png(charToRaw(svg), width = px, height = px)
  image <- png::readPNG(rendered)
  assign(key, image, envir = icon_cache)
  image
}

draw_icon <- function(name, x, y, size_mm = 5.2, colour = COL[["ink"]]) {
  grid.raster(load_icon(name, colour), x = unit(x, "npc"), y = unit(y, "npc"),
              width = unit(size_mm, "mm"), height = unit(size_mm, "mm"),
              interpolate = TRUE)
}

load_generated <- function(name) {
  if (exists(name, envir = generated_cache, inherits = FALSE)) {
    return(get(name, envir = generated_cache, inherits = FALSE))
  }
  path <- file.path(generated_icon_dir, paste0(name, ".png"))
  if (!file.exists(path)) stop("Missing generated icon asset: ", path)
  image <- png::readPNG(path)
  assign(name, image, envir = generated_cache)
  image
}

draw_generated <- function(name, x, y, size_mm = 7.2) {
  grid.raster(load_generated(name), x = unit(x, "npc"), y = unit(y, "npc"),
              width = unit(size_mm, "mm"), height = unit(size_mm, "mm"),
              interpolate = TRUE)
}

generated_node <- function(name, x, y, title, detail = "", colour = COL[["blue"]],
                           card_fill = COL[["white"]], card_w = 0.048,
                           card_h = 0.048, image_mm = 6.0, title_size = 4.5,
                           detail_size = 3.8) {
  grid.roundrect(x = unit(x, "npc"), y = unit(y, "npc"),
                 width = unit(card_w, "npc"), height = unit(card_h, "npc"),
                 r = unit(1.1, "mm"),
                 gp = gpar(fill = card_fill, col = colour, lwd = 0.55))
  draw_generated(name, x, y, image_mm)
  txt(title, x, y - 0.036, title_size, COL[["ink"]], "bold")
  if (nzchar(detail)) txt(detail, x, y - 0.056, detail_size, COL[["muted"]])
}

icon_disc <- function(name, x, y, radius_mm = 4.5, icon_mm = 4.4,
                      colour = COL[["blue"]], fill = COL[["blue_pale"]],
                      lwd = 0.65) {
  grid.circle(x = unit(x, "npc"), y = unit(y, "npc"), r = unit(radius_mm, "mm"),
              gp = gpar(fill = fill, col = colour, lwd = lwd))
  draw_icon(name, x, y, icon_mm, colour)
}

module_node <- function(name, x, y, title, detail = "", colour = COL[["blue"]],
                        fill = COL[["white"]], radius = 4.3, icon_mm = 4.2,
                        title_size = 4.7, detail_size = 4.0) {
  icon_disc(name, x, y, radius, icon_mm, colour, fill, 0.6)
  txt(title, x, y - 0.036, title_size, COL[["ink"]], "bold")
  if (nzchar(detail)) txt(detail, x, y - 0.056, detail_size, COL[["muted"]])
}

source_row <- function(name, x, y, title, detail, colour, fill) {
  icon_disc(name, x, y, 3.6, 3.5, colour, fill, 0.55)
  txt(title, x + 0.028, y + 0.008, 4.8, COL[["ink"]], "bold", "left")
  txt(detail, x + 0.028, y - 0.015, 4.0, COL[["muted"]], "plain", "left")
}

stage_title <- function(stage, title, left, top, colour, route = "") {
  grid.circle(x = unit(left + 0.018, "npc"), y = unit(top - 0.019, "npc"),
              r = unit(2.5, "mm"), gp = gpar(fill = colour, col = NA))
  txt(stage, left + 0.018, top - 0.019, 4.5, COL[["white"]], "bold")
  txt(title, left + 0.041, top - 0.019, 5.1, COL[["ink"]], "bold", "left")
  if (nzchar(route)) {
    txt(route, left + 0.041, top - 0.045, 3.2, COL[["muted"]], "plain", "left")
  }
}

insight_card <- function(name, left, bottom, title, detail, colour, fill) {
  panel_box(left, bottom, 0.220, 0.065, fill, COL[["border"]], 0.4)
  draw_icon(name, left + 0.026, bottom + 0.0325, 4.0, colour)
  txt(title, left + 0.050, bottom + 0.041, 4.7, COL[["ink"]], "bold", "left")
  txt(detail, left + 0.050, bottom + 0.019, 3.9, COL[["muted"]], "plain", "left")
}

draw_figure <- function() {
  grid.newpage()
  grid.rect(gp = gpar(fill = COL[["white"]], col = NA))

  txt("游戏创意雷达：从多源信息到游戏设计洞察", 0.03, 0.975,
      11.8, COL[["ink"]], "bold", "left")
  txt("n8n + Horizon API 主链：来源定义观察范围，内容路由主题，候选经证据与编辑后发布。",
      0.03, 0.946, 5.9, COL[["muted"]], "plain", "left")
  rule(0.03, 0.925, 0.97, 0.925, COL[["border"]], 0.8)

  # Column frames and headers.
  panel_box(0.025, 0.045, 0.205, 0.855, COL[["white"]], COL[["border"]], 0.65)
  panel_box(0.245, 0.045, 0.445, 0.855, COL[["white"]], COL[["border"]], 0.65)
  panel_box(0.705, 0.045, 0.270, 0.855, COL[["white"]], COL[["border"]], 0.65)
  section_title("a", "输入与采集策略", 0.032, 0.885)
  section_title("b", "内容理解与筛选", 0.252, 0.885)
  section_title("c", "设计洞察与发布", 0.712, 0.885)

  # a | Observation scope, cadence and source governance.
  panel_box(0.035, 0.575, 0.185, 0.285, COL[["light"]], COL[["border"]], 0.45)
  sub_title("a(i)", "多源发现池", 0.035, 0.86, COL[["teal"]])
  txt("约 300 RSS / 100 X 路由", 0.052, 0.815, 6.9, COL[["teal"]], "bold", "left")
  txt("来源标签只说明出处，不决定主题板块", 0.052, 0.787, 4.2, COL[["muted"]], "plain", "left")
  draw_generated("source-pool", 0.192, 0.808, 9.5)
  source_row("rss", 0.060, 0.744, "原生 RSS / Atom", "开发复盘 · 研究 · 行业", COL[["teal"]], COL[["teal_pale"]])
  source_row("link", 0.060, 0.682, "RSSHub 路由", "站点聚合 · 频道订阅", COL[["blue"]], COL[["blue_pale"]])
  source_row("at-sign", 0.060, 0.620, "X 路由（RSSHub）", "高信号账号 · 回复线索", COL[["blue"]], COL[["blue_pale"]])
  rule(0.050, 0.592, 0.205, 0.592, COL[["border"]], 0.45)
  txt("来源只负责发现，主题由内容决定", 0.052, 0.585, 4.0, COL[["muted"]], "plain", "left")

  panel_box(0.035, 0.365, 0.185, 0.175, COL[["white"]], COL[["border"]], 0.45)
  sub_title("a(ii)", "调度节奏", 0.035, 0.540, COL[["blue"]])
  source_row("clock-3", 0.060, 0.492, "Daily", "24 h · 约 190 路由", COL[["muted"]], COL[["light"]])
  source_row("refresh-cw", 0.060, 0.442, "Weekly", "168 h · 130 RSS", COL[["blue"]], COL[["blue_pale"]])
  source_row("archive", 0.060, 0.392, "Reserve", "720 h · 80 RSS", COL[["gold"]], COL[["gold_pale"]])

  panel_box(0.035, 0.070, 0.185, 0.260, COL[["white"]], COL[["border"]], 0.45)
  sub_title("a(iii)", "来源治理", 0.035, 0.330, COL[["red"]])
  source_row("layers-3", 0.060, 0.282, "来源池分层", "daily / weekly / reserve", COL[["gold"]], COL[["gold_pale"]])
  source_row("shield-check", 0.060, 0.225, "端点健康", "可用性与域名安全", COL[["red"]], COL[["red_pale"]])
  source_row("link", 0.060, 0.168, "URL 归一化", "跨来源合并同一内容", COL[["teal"]], COL[["teal_pale"]])
  source_row("database", 0.060, 0.111, "历史去重", "避免重复进入候选集", COL[["blue"]], COL[["blue_pale"]])

  # b | Three numbered content-intelligence stages.
  panel_box(0.255, 0.680, 0.425, 0.180, COL[["teal_pale"]], COL[["border"]], 0.45)
  stage_title("1", "采集与标准化", 0.255, 0.860, COL[["teal"]], "/fetch")
  txt("多源发现池", 0.270, 0.792, 4.3, COL[["muted"]], "plain", "left")
  xs <- c(0.305, 0.382, 0.459, 0.536, 0.613)
  acq_icons <- c("download", "scan-search", "link", "shield-check", "archive")
  acq_titles <- c("抓取", "解析", "合并", "安全", "标准条目")
  acq_details <- c("多源并发", "正文 / 摘要", "URL unique", "域名 allowlist", "统一 schema")
  for (i in seq_along(xs)) {
    if (i == 1) {
      generated_node("acquisition", xs[[i]], 0.765, acq_titles[[i]], acq_details[[i]],
                     COL[["teal"]], COL[["white"]], 0.052, 0.052, 7.0, 4.2, 3.7)
    } else {
      module_node(acq_icons[[i]], xs[[i]], 0.765, acq_titles[[i]], acq_details[[i]],
                  COL[["teal"]], COL[["white"]], 3.8, 3.7, 4.2, 3.7)
    }
    if (i < length(xs)) flow_arrow(xs[[i]] + 0.028, 0.765, xs[[i + 1]] - 0.028, 0.765, COL[["teal"]], 0.55)
  }

  panel_box(0.255, 0.390, 0.425, 0.265, COL[["blue_pale"]], COL[["border"]], 0.45)
  stage_title("2", "内容路由与灵感评分", 0.255, 0.655, COL[["blue"]], "/score")
  module_node("file-text", 0.292, 0.560, "标题 + 正文", "单条 item", COL[["muted"]], COL[["white"]], 3.9, 3.8, 4.1, 3.6)
  generated_node("classification-scoring", 0.360, 0.560, "分类器", "LLM prompt", COL[["blue"]], COL[["white"]], 0.052, 0.052, 7.0, 4.1, 3.6)
  rule(0.389, 0.560, 0.420, 0.560, COL[["blue"]], 0.55)
  txt("六个主题板（互斥路由）", 0.495, 0.615, 4.2, COL[["blue"]], "bold")
  topic_icons <- c("gameplay-mechanics", "world-level", "narrative-culture", "visual-experience", "production-tech", "player-market")
  topic_titles <- c("玩法", "世界", "叙事", "视觉", "技术", "玩家")
  topic_x <- c(0.440, 0.500, 0.560, 0.440, 0.500, 0.560)
  topic_y <- c(0.555, 0.555, 0.555, 0.472, 0.472, 0.472)
  rule(0.420, 0.560, 0.420, 0.600, COL[["border"]], 0.5)
  rule(0.420, 0.600, 0.590, 0.600, COL[["border"]], 0.5)
  for (i in seq_along(topic_icons)) {
    bus_y <- if (i <= 3) 0.600 else 0.448
    if (i == 4) {
      rule(0.505, 0.600, 0.505, 0.448, COL[["border"]], 0.5)
      rule(0.420, 0.448, 0.590, 0.448, COL[["border"]], 0.5)
    }
    rule(topic_x[[i]], bus_y, topic_x[[i]], topic_y[[i]] + 0.029, COL[["border"]], 0.45)
    generated_node(topic_icons[[i]], topic_x[[i]], topic_y[[i]], topic_titles[[i]], "", COL[["blue"]], COL[["white"]], 0.040, 0.040, 5.1, 3.8, 3.4)
  }
  module_node("sparkles", 0.630, 0.555, "评分", "7–10 + rationale", COL[["gold"]], COL[["gold_pale"]], 4.0, 3.9, 4.2, 3.5)
  flow_arrow(0.590, 0.560, 0.601, 0.560, COL[["blue"]], 0.55)

  panel_box(0.255, 0.070, 0.425, 0.285, COL[["white"]], COL[["border"]], 0.45)
  stage_title("3", "筛选、去重与重评", 0.255, 0.355, COL[["red"]], "/filter")
  xs <- c(0.315, 0.420, 0.525, 0.630)
  filter_icons <- c("funnel", "layers-3", "message-square-text", "archive")
  filter_titles <- c("阈值", "语义去重", "回复重评", "过滤候选")
  filter_details <- c("≥ 7.0", "同板块", "X replies", "filtered")
  filter_colours <- c(COL[["blue"]], COL[["blue"]], COL[["teal"]], COL[["red"]])
  for (i in seq_along(xs)) {
    module_node(filter_icons[[i]], xs[[i]], 0.235, filter_titles[[i]], filter_details[[i]],
                filter_colours[[i]], if (i == length(xs)) COL[["red_pale"]] else COL[["white"]],
                3.8, 3.7, 4.2, 3.6)
    if (i < length(xs)) flow_arrow(xs[[i]] + 0.028, 0.235, xs[[i + 1]] - 0.028, 0.235, COL[["border"]], 0.5)
  }
  txt("阈值、板块内语义去重与上下文重评，形成进入研究阶段的候选集", 0.270, 0.098, 3.9, COL[["muted"]], "plain", "left")

  # c | Evidence, design translation and delivery.
  panel_box(0.715, 0.690, 0.250, 0.170, COL[["teal_pale"]], COL[["border"]], 0.45)
  stage_title("4", "证据检索与引用", 0.715, 0.860, COL[["teal"]], "/research")
  generated_node("evidence-enrichment", 0.765, 0.765, "背景检索", "工具规划", COL[["teal"]], COL[["white"]], 0.050, 0.050, 7.0, 4.0, 3.4)
  module_node("link", 0.840, 0.765, "引用校验", "来源对应主张", COL[["teal"]], COL[["white"]], 3.7, 3.6, 4.0, 3.4)
  module_node("file-check", 0.915, 0.765, "证据包", "可引用背景", COL[["red"]], COL[["red_pale"]], 3.7, 3.6, 4.0, 3.4)
  flow_arrow(0.794, 0.765, 0.811, 0.765, COL[["teal"]], 0.5)
  flow_arrow(0.869, 0.765, 0.886, 0.765, COL[["teal"]], 0.5)

  panel_box(0.715, 0.380, 0.250, 0.285, COL[["blue_pale"]], COL[["border"]], 0.45)
  stage_title("5", "候选评估、终审与设计转译", 0.715, 0.665, COL[["blue"]], "/evaluate → /select → /enrich")
  insight_card("sparkles", 0.730, 0.565, "评估候选", "设计潜力 · 证据质量", COL[["blue"]], COL[["white"]])
  insight_card("users", 0.730, 0.480, "终审选择 10 条", "≥4 主题 · ≤2 / 来源", COL[["gold"]], COL[["gold_pale"]])
  insight_card("gamepad-2", 0.730, 0.395, "编辑成稿", "事实 · 新鲜关系 · 游戏问题", COL[["red"]], COL[["red_pale"]])
  flow_arrow(0.840, 0.560, 0.840, 0.550, COL[["border"]], 0.45)
  flow_arrow(0.840, 0.475, 0.840, 0.465, COL[["border"]], 0.45)
  txt("不满足事实、证据或设计价值的候选直接退稿", 0.730, 0.387, 3.3, COL[["red"]], "plain", "left")

  panel_box(0.715, 0.070, 0.250, 0.275, COL[["red_pale"]], COL[["border"]], 0.45)
  stage_title("6", "多模态报告与分发", 0.715, 0.345, COL[["red"]], "/report → /feishu")
  generated_node("report-assembly", 0.765, 0.265, "完整报告", "Markdown + HTML", COL[["red"]], COL[["white"]], 0.052, 0.052, 7.0, 4.0, 3.4)
  generated_node("concept-art", 0.885, 0.265, "封面 / 概念图", "AI images", COL[["gold"]], COL[["gold_pale"]], 0.052, 0.052, 7.0, 4.0, 3.4)
  module_node("monitor-down", 0.765, 0.155, "卡片组", "1080 × 1440", COL[["blue"]], COL[["white"]], 3.8, 3.7, 4.0, 3.4)
  generated_node("delivery", 0.885, 0.155, "飞书分发", "Card / webhook", COL[["red"]], COL[["white"]], 0.052, 0.052, 8.5, 4.0, 3.4)
  flow_arrow(0.765, 0.225, 0.765, 0.195, COL[["red"]], 0.5)
  flow_arrow(0.885, 0.225, 0.885, 0.195, COL[["red"]], 0.5)
  flow_arrow(0.796, 0.155, 0.854, 0.155, COL[["red"]], 0.5)
  txt("Markdown · HTML · PNG · webhook", 0.840, 0.088, 4.0, COL[["muted"]], "bold")

  # Numbered stage flow across and down the page.
  orth_arrow(list(c(0.220, 0.735), c(0.238, 0.735), c(0.238, 0.765), c(0.255, 0.765)), COL[["teal"]], 0.75)
  flow_arrow(0.467, 0.675, 0.467, 0.660, COL[["blue"]], 0.65)
  flow_arrow(0.467, 0.385, 0.467, 0.360, COL[["red"]], 0.65)
  orth_arrow(list(c(0.650, 0.235), c(0.695, 0.235), c(0.695, 0.765), c(0.715, 0.765)), COL[["blue"]], 0.7)
  flow_arrow(0.840, 0.685, 0.840, 0.670, COL[["blue"]], 0.65)
  flow_arrow(0.840, 0.375, 0.840, 0.350, COL[["red"]], 0.65)
}

export_figure <- function() {
  svglite::svglite(paste0(out_base, ".svg"), width = width_in, height = height_in,
                   bg = "white", system_fonts = list(sans = FONT))
  draw_figure()
  dev.off()

  grDevices::cairo_pdf(paste0(out_base, ".pdf"), width = width_in, height = height_in,
                       family = FONT, bg = "white")
  draw_figure()
  dev.off()

  ragg::agg_png(paste0(out_base, ".png"), width = width_in, height = height_in,
                units = "in", res = 300, background = "white")
  draw_figure()
  dev.off()

  ragg::agg_tiff(paste0(out_base, ".tiff"), width = width_in, height = height_in,
                 units = "in", res = 600, background = "white", compression = "lzw")
  draw_figure()
  dev.off()
}

export_figure()
message("Wrote: ", normalizePath(out_base, mustWork = FALSE), ".{svg,pdf,png,tiff}")
