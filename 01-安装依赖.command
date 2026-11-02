#!/bin/bash
cd "$(dirname "$0")" || exit 1
/bin/bash scripts/install.sh
result=$?
if [ "$result" -ne 0 ]; then echo "操作失败，请阅读上面的提示。"; fi
read -r -p "按回车关闭…" _reply
exit "$result"
