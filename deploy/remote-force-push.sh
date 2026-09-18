# AI生成
#!/bin/bash
cd /home/nathan/bridge-python
git pull origin main --rebase --allow-unrelated-histories 2>&1
if [ $? -ne 0 ]; then
  echo "PULL_FAILED, force pushing"
  git push -u origin main --force 2>&1
else
  echo "PULL_OK, pushing"
  git push -u origin main 2>&1
fi
git tag -a v0.1 -m "v0.1: Initial Python release" 2>&1
git push origin v0.1 2>&1
echo "PUSH_DONE"