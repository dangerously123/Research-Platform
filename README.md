# Research-Platform

# 1. 确认当前改动
git status

# 2. 将指定文件加入暂存区
git add 文件名

# 或将当前目录下所有需要提交的改动加入暂存区
git add .

# 3. 创建本地提交
git commit -m "简要说明本次修改内容"

# 4. 推送至 GitHub
git push

#  整个文件 推送至 GitHub
git status：确认有哪些变更；
git add .：递归暂存当前目录及所有子目录中的文件；
git diff --staged：提交前检查将要上传的内容；
git commit -m "..."：提交到本地 Git 历史；
git push：推送到 GitHub。
