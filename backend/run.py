import uvicorn

if __name__ == "__main__":
    # 注意:不用 reload=True —— Windows 上 WatchFiles reloader 会在代码变更后挂掉(worker 无法重新拉起)
    uvicorn.run("app.main:app", host="127.0.0.1", port=5278)
