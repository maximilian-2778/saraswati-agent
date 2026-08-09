"""故事、故事设定副本与消息。"""

from backend.routers._select import routes_with_tags

router = routes_with_tags({"chats", "story-bindings", "character", "world-book", "messages"})
