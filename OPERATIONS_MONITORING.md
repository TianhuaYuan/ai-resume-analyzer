# PDF 导出与监控部署

## WeasyPrint（中文 PDF）

后端镜像已安装 `weasyprint` Python 包、Cairo/Pango/GDK-Pixbuf 运行库和 Noto CJK 字体。重新构建 backend 镜像后，`GET /api/v1/resumes/{id}/export?format=pdf` 可以生成中文 PDF。

### Linux/Docker（推荐）

`backend/Dockerfile` 已包含 WeasyPrint 所需的 Debian Bookworm 原生库：
`libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 shared-mime-info fontconfig fonts-noto-cjk`，并执行 `fc-cache -f`。

```powershell
docker compose -f docker-compose.prod.yml build backend
docker compose -f docker-compose.prod.yml up -d
```

### Windows 本机开发

仅执行 `pip install weasyprint` 不够，还必须让 DLL 搜索路径中存在 GTK/Pango/Cairo。可使用 MSYS2：

```powershell
winget install MSYS2.MSYS2
# 在 MSYS2 UCRT64 终端执行
pacman -S --needed mingw-w64-ucrt-x86_64-gtk3 mingw-w64-ucrt-x86_64-pango mingw-w64-ucrt-x86_64-cairo mingw-w64-ucrt-x86_64-gdk-pixbuf
```

启动后端前，把 `C:\msys64\ucrt64\bin` 加入当前进程的 `PATH`，再验证：

```powershell
$env:Path = "C:\msys64\ucrt64\bin;$env:Path"
python -c "from weasyprint import HTML; HTML(string='<p>中文简历测试</p>').write_pdf('weasyprint-smoke.pdf')"
```

如果不希望维护 Windows 原生 DLL，直接使用 Docker 是更稳定的开发/部署路径。

## Prometheus + Grafana

生产/预发布先启动业务 compose，再启动监控 compose；两者共享固定的 `resume-network`：

```powershell
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.monitoring.yml up -d
```

监控 compose 默认只绑定 `127.0.0.1`（Grafana `3000`、Prometheus `9090`）。需要反向代理或内网访问时，显式设置 `GRAFANA_BIND` / `PROMETHEUS_BIND`，不要无意暴露到公网。

Prometheus 容器会以 `0600` 权限写入 `METRICS_TOKEN`，并通过 `bearer_token_file` 抓取后端 `/metrics`。Grafana datasource UID 固定为 `prometheus`，dashboard 由 provisioning 自动注册。

生产/预发布必须设置非空的 `METRICS_TOKEN` 和 `GRAFANA_ADMIN_PASSWORD`；本地开发可留空 metrics token。
