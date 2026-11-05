"""Public endpoint only: compare TLS modes without keys or insecure certificate bypass."""
import ssl
import httpx

print(ssl.OPENSSL_VERSION, flush=True)
for name in ("httpx-default", "system-roots", "tls12"):
    context = True if name == "httpx-default" else ssl.create_default_context()
    if name == "tls12":
        context.maximum_version = ssl.TLSVersion.TLSv1_2
    try:
        response = httpx.get("https://api.siliconflow.cn/v1/models", verify=context, timeout=8)
        print(name, response.status_code, flush=True)
    except Exception as exc:
        print(name, type(exc).__name__, str(exc)[:150], flush=True)
