"""HTTP client for the Omada controller internal web API (stdlib only)."""
import json
import ssl
import urllib.error
import urllib.request


class OmadaError(Exception):
    pass


class OmadaClient:
    def __init__(self, base_url, username, password, controller_id=None,
                 site="Default", verify_tls=False, dry_run=False, verbose=False):
        self.base = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.cid = controller_id
        self.site_ref = site
        self.site_id = None
        self.dry_run = dry_run
        self.verbose = verbose
        self.token = None
        self.cookie = None
        if verify_tls:
            self._ctx = ssl.create_default_context()
        else:
            self._ctx = ssl.create_default_context()
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    # -- low level ----------------------------------------------------------
    def _raw(self, method, url, body=None, authed=True):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if authed and self.token:
            req.add_header("Csrf-Token", self.token)
        if authed and self.cookie:
            req.add_header("Cookie", self.cookie)
        if self.verbose:
            print(f"  {method} {url}" + (f"  {json.dumps(body)}" if body else ""))
        try:
            resp = urllib.request.urlopen(req, context=self._ctx, timeout=20)
        except urllib.error.HTTPError as e:
            raise OmadaError(f"HTTP {e.code} on {url}: {e.read()[:200]!r}")
        except urllib.error.URLError as e:
            raise OmadaError(f"cannot reach {url}: {e.reason}")
        sc = resp.headers.get("Set-Cookie")
        if sc:
            self.cookie = sc.split(";")[0]
        text = resp.read().decode()
        try:
            j = json.loads(text)
        except json.JSONDecodeError:
            raise OmadaError(f"non-JSON response from {url}: {text[:120]}")
        ec = j.get("errorCode")
        if ec not in (0, None):
            raise OmadaError(f"API errorCode={ec}: {j.get('msg')} ({url})")
        return j.get("result", j)

    def _api(self, method, path, body=None):
        return self._raw(method, f"{self.base}/{self.cid}/api/v2{path}", body)

    # -- connect ------------------------------------------------------------
    def connect(self):
        if not self.cid:
            self.cid = self._discover_cid()
        self.token = self._raw(
            "POST", f"{self.base}/{self.cid}/api/v2/login",
            {"username": self.username, "password": self.password},
            authed=False)["token"]
        self.site_id = self._resolve_site()
        return self

    def _discover_cid(self):
        info = self._raw("GET", f"{self.base}/api/info", authed=False)
        cid = info.get("omadacId") or info.get("controllerId")
        if not cid:
            raise OmadaError(
                "could not auto-discover controller_id from /api/info; set it "
                "in the config (it's the hex string in the controller URL).")
        return cid

    def _resolve_site(self):
        ref = self.site_ref
        if isinstance(ref, str) and len(ref) == 24 and all(
                c in "0123456789abcdef" for c in ref.lower()):
            return ref
        for s in self.sites():
            if s.get("name", "").lower() == str(ref).lower():
                return s["id"]
        raise OmadaError(f"site '{ref}' not found on this controller")

    # -- site-scoped helpers ------------------------------------------------
    def _s(self, path):
        return f"/sites/{self.site_id}{path}"

    def get(self, path):
        return self._api("GET", self._s(path))

    def get_global(self, path):
        return self._api("GET", path)

    def patch(self, path, body):
        if self.dry_run:
            print(f"  [dry-run] PATCH {self._s(path)}  {json.dumps(body)}")
            return {"_dry_run": True}
        return self._api("PATCH", self._s(path), body)

    def post(self, path, body=None):
        if self.dry_run:
            print(f"  [dry-run] POST {self._s(path)}  {json.dumps(body)}")
            return {"_dry_run": True}
        return self._api("POST", self._s(path), body)

    def delete(self, path):
        if self.dry_run:
            print(f"  [dry-run] DELETE {self._s(path)}")
            return {"_dry_run": True}
        return self._api("DELETE", self._s(path))

    def paginate(self, path, page_size=100, extra=""):
        """Collect all rows from a paginated list endpoint."""
        rows, page = [], 1
        while True:
            sep = "&" if "?" in path else "?"
            q = f"{path}{sep}currentPage={page}&currentPageSize={page_size}{extra}"
            res = self.get(q)
            data = res.get("data", []) if isinstance(res, dict) else []
            rows.extend(data)
            total = res.get("totalRows", len(rows)) if isinstance(res, dict) else len(rows)
            if len(rows) >= total or not data:
                break
            page += 1
        return rows

    # -- convenience --------------------------------------------------------
    def sites(self):
        return self._api("GET", "/sites?currentPage=1&currentPageSize=100")["data"]

    def controller_status(self):
        return self._api("GET", "/maintenance/controllerStatus")

    def overview(self):
        return self.get("/dashboard/overviewDiagram")

    def devices(self):
        return self.get("/devices")

    def eap(self, mac):
        return self.get(f"/eaps/{mac}")

    def eap_patch(self, mac, body):
        return self.patch(f"/eaps/{mac}", body)

    def clients(self, active=True):
        f = "&filters.active=true" if active else "&filters.active=false"
        return self.paginate("/clients", extra=f)

    def known_clients(self):
        return self.paginate("/insight/clients")

    def setting(self):
        return self.get("/setting")

    def setting_patch(self, body):
        return self.patch("/setting", body)

    def wlan_groups(self):
        return self.get("/setting/wlans")["data"]

    def ssids(self, wlan_id):
        return self.get(f"/setting/wlans/{wlan_id}/ssids")["data"]

    def ssid_patch(self, wlan_id, ssid_id, body):
        return self.patch(f"/setting/wlans/{wlan_id}/ssids/{ssid_id}", body)

    def lan_networks(self):
        return self.paginate("/setting/lan/networks")

    def alerts(self):
        return self.paginate("/alerts")

    def events(self):
        return self.paginate("/events")
