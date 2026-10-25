"""留言板改造文案（review-report P1-12 / C-16 / A-3）。

命名空间：``board2.*``，与主表既有的 ``board.*`` 分开。已有的
``board.title`` / ``board.rule_*`` / ``board.comment_count`` 等继续复用，
这里只补这次改造新增的提示语与空状态文案。
"""

T = {
    "zh": {
        # 页头：规则折叠（不再占首屏）
        "board2.rules_summary": "发帖规则",
        # 登录横条：整页只出现一次，且「登录」必须是链接
        "board2.login_action": "登录",
        "board2.login_tail": "后可点赞、评论（注册需邀请码）",
        # 保留期徽章：琥珀色，说明是「图片」的保留期并给出日期
        "board2.retention": "图片保留剩余 {days} 天（至 {date}）",
        "board2.retention_one": "图片保留剩余 1 天（至 {date}）",
        "board2.retention_today": "图片今天到期",
        "board2.retention_short": "剩余 {days} 天",
        "board2.retention_short_urgent": "剩余 {days} 天（至 {date}）",
        # meta 行（13px）：点赞与评论同语法、同色文字链接
        "board2.like_aria": "点赞（当前 {count} 个赞）",
        "board2.like_aria_one": "点赞（当前 1 个赞）",
        "board2.comment_count": "{count} 条评论",
        "board2.comment_count_one": "1 条评论",
        "board2.comment_aria": "查看 {count} 条评论",
        "board2.comment_aria_one": "查看 1 条评论",
        # 空状态：给下一步动作
        "board2.empty_title": "还没有人分享大牌",
        "board2.empty_body": "留言板靠大家最近和到的大牌照片撑起来。发布第一张，让其他玩家来点赞、评论。",
        "board2.empty_cta": "发布第一张大牌",
        "board2.empty_rules": "看看发帖规则",
        # 详情页
        "board2.byline": "由 {name} 发布于 {time}",
    },
    "en": {
        "board2.rules_summary": "Posting rules",
        "board2.login_action": "Log in",
        "board2.login_tail": " to like and comment (an invite code is needed to register)",
        "board2.retention": "Photo kept for {days} more days (until {date})",
        "board2.retention_one": "Photo kept for 1 more day (until {date})",
        "board2.retention_today": "Photo expires today",
        "board2.retention_short": "{days} days left",
        "board2.retention_short_urgent": "{days} days left (until {date})",
        "board2.like_aria": "Like (currently {count} likes)",
        "board2.like_aria_one": "Like (currently 1 like)",
        "board2.comment_count": "{count} comments",
        "board2.comment_count_one": "1 comment",
        "board2.comment_aria": "View {count} comments",
        "board2.comment_aria_one": "View 1 comment",
        "board2.empty_title": "No big hands shared yet",
        "board2.empty_body": "This board grows from the big hands the community has won lately. Share the first photo and let other players cheer you on.",
        "board2.empty_cta": "Share the first big hand",
        "board2.empty_rules": "Read the posting rules",
        "board2.byline": "Posted by {name} on {time}",
    },
}
