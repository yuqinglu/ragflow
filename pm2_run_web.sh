cd web
npx pm2 start npm --name "ragflow-web" -- run dev

# 管理命令都加npx前缀
npx pm2 list
npx pm2 logs ragflow-web
npx pm2 stop ragflow-web