# techreg_client.py
import json, os, base64, time
from typing import Any, Dict, List, Optional, Union
import requests

class TechRegClient:
    def __init__(
        self,
        base_url: str = "https://techreg.gov.kz/Synergy/rest/api",
        cookies: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        verify: Union[bool, str] = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "TechRegClient/1.2",
            "Referer": "https://techreg.gov.kz/index/",
            "Origin": "https://techreg.gov.kz",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Language": "ru,ru-RU;q=0.9",
            "X-KL-KFA-Ajax-Request": "Ajax_Request",
        })
        if cookies:
            self.session.cookies.update(cookies)
        # Разрешим переопределять таймаут через ENV
        self.timeout = int(os.getenv("TECHREG_TIMEOUT", timeout))
        self.verify = verify

        # ----- Authorization: Basic -----
        basic_b64 = None
        ck = (cookies or {}).get("constructor_creds_for_index") if cookies else None
        if not ck:
            ck = self.session.cookies.get("constructor_creds_for_index")
        if ck:
            basic_b64 = ck
        env_basic = os.getenv("TECHREG_BASIC")
        if not basic_b64 and env_basic:
            basic_b64 = base64.b64encode(env_basic.encode()).decode() if ":" in env_basic else env_basic
        if basic_b64:
            self.session.headers["Authorization"] = f"Basic {basic_b64}"

    # ---------- helpers ----------
    @staticmethod
    def _json_fix(text: str):
        t = text.strip()
        if t.startswith('"data":'):
            return json.loads("{"+t+"}")
        return json.loads(t)

    def _request(self, path: str, params: Optional[Dict[str, Union[str,int]]] = None,
                 timeout: Optional[int] = None, retries: int = 0, backoff: float = 0.75) -> Any:
        """GET с ретраями на таймаутах/сетевых сбоях."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_err = None
        for attempt in range(retries + 1):
            try:
                r = self.session.get(url, params=params or {}, timeout=timeout or self.timeout, verify=self.verify)
                r.raise_for_status()
                ct = r.headers.get("Content-Type", "")
                if "application/json" in ct:
                    return r.json()
                return self._json_fix(r.text)
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
                last_err = e
                if attempt < retries:
                    time.sleep(backoff * (2 ** attempt))
                    continue
                raise
            except Exception as e:
                last_err = e
                raise
        if last_err:
            raise last_err

    def _get(self, path: str, params: Optional[Dict[str, Union[str,int]]] = None) -> Any:
        return self._request(path, params=params)

    def warmup(self):
        try:
            self.session.get("https://techreg.gov.kz/index/", timeout=self.timeout, verify=self.verify)
        except Exception:
            pass
        xsrf = self.session.cookies.get("XSRF-TOKEN")
        if xsrf:
            self.session.headers["X-XSRF-TOKEN"] = xsrf

    # ---------- diagnostics ----------
    def person_auth(self) -> Any:
        return self._get("person/auth")

    def list_registries(self, locale: str = "ru") -> Any:
        return self._get("registry/list", {"locale": locale})

    def registry_info(self, code: Optional[str] = None, registry_id: Optional[str] = None, locale: str = "ru") -> Any:
        p: Dict[str, Union[str,int]] = {"locale": locale}
        if code: p["code"] = code
        if registry_id: p["registryID"] = registry_id
        return self._get("registry/info", p)

    def registry_filters(
        self,
        registry_code: Optional[str] = None,
        code: Optional[str] = None,
        registry_id: Optional[str] = None,
        locale: str = "ru",
    ) -> Any:
        p: Dict[str, Union[str, int]] = {"locale": locale}
        if registry_code:
            p["registryCode"] = registry_code
        elif registry_id:
            p["registryID"] = registry_id
        elif code:
            p["code"] = code
        return self._get("registry/filters", p)

    def get_player_html(self, document_id) -> str | None:
            """
            Возвращает HTML страницы плеера формы, где значения лежат в div[data-asformid="*.text.*"].
            Пробуем несколько URL — берём первый, где внутри есть asf-playerView.
            """
            cand_urls = [
                f"{self.base_url}/constructor/formPlayerPage?documentID={document_id}",
                f"{self.base_url}/formPlayerPage?documentID={document_id}",
                f"{self.base_url}/index/?documentID={document_id}&page=formPlayerPage",
            ]
            for url in cand_urls:
                r = self.session.get(url, timeout=30, verify=self.verify)
                if r.ok and "asf-playerView" in r.text:
                    return r.text
            return None

    def registry_count(self, registry_code: str, searchField: Optional[str] = None,
                       key: Optional[str] = None, locale: str = "ru") -> Any:
        p: Dict[str, Union[str,int]] = {"registryCode": registry_code, "locale": locale}
        if searchField: p["searchField"] = searchField
        if key: p["key"] = key
        return self._get("registry/count_data", p)

    # ---------- main APIs ----------
    # techreg_client.py (фрагмент)

    def registry_data(
        self,
        registry_code: str,
        page: int = 0,
        size: int = 50,
        fields: Optional[List[str]] = None,
        searchField: Optional[str] = None,
        key: Optional[str] = None,
        locale: str = "ru",
        heavy: bool = False,
        field: Optional[str] = None,
        condition: Optional[str] = None,
        value: Optional[str] = None,
    ) -> Any:
        p: Dict[str, Union[str,int]] = {
            "registryCode": registry_code,
            "page": page, "size": size, "locale": locale
        }
        if fields: p["fields"] = ",".join(fields)

        # приоритет: индексный фильтр
        if field and condition and (value is not None):
            p["field"] = field
            p["condition"] = condition
            p["value"] = value
        else:
            if searchField: p["searchField"] = searchField
            if key is not None: p["key"] = key

        return self._request(
            "registry/data_ext",
            params=p,
            timeout=(90 if heavy else None),
            retries=(2 if heavy else 0),
        )

    def dictionary(self, code: str, locale: str = "ru") -> Any:
        return self._get("dictionary/get_by_code", {"dictionaryCode": code, "locale": locale})

    def asforms_data(self, data_id: Union[int,str]) -> Any:
        return self._get(f"asforms/data/{data_id}")

    def asforms_collate(self, registry_document_id: str,
                        collation_group: Optional[str] = None, version: int = 4) -> Any:
        p: Dict[str, Union[str,int]] = {"registryDocumentId": registry_document_id, "version": version}
        if collation_group: p["collationGroup"] = collation_group
        return self._get("asforms/form/collate", p)

    @staticmethod
    def load_cookies_from_file(path: str) -> Dict[str, str]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {c["name"]: c["value"] for c in data if "name" in c and "value" in c}
        raise ValueError("Unsupported cookie format")

    # ---------- High-level ----------
    def get_sbkts_by_number(self, number: str) -> Dict[str, Any]:
        num = " ".join((number or "").split())

        def search_fast(q: str):
            # минимальный набор полей => быстрее
            return self.registry_data(
                "registry_certificate_safety_vehicle_structure",
                page=0, size=1, heavy=True,
                fields=["textbox_number","documentID","dataUUID"],
                # ⚡️ индексный фильтр — вместо searchField/key
                field="textbox_number", condition="TEXT_EQUALS", value=q,
            )

        reg = search_fast(num)

        if (not reg) or (not reg.get("result")):
            # кириллица → латиница (частые путаницы)
            map_c2l = {"А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"C","Т":"T","Х":"X","У":"Y"}
            alt = "".join(map_c2l.get(ch, ch) for ch in num)
            if alt != num:
                reg = search_fast(alt)

        if not reg or not reg.get("result"):
            return {"ok": False, "reason": "not_found_in_registry", "searched": num}

        rec = reg["result"][0]
        document_id = rec.get("documentID")
        data_uuid   = rec.get("dataUUID")

        # Детали карточки
        detail = None
        if data_uuid:
            try:
                detail = self.asforms_data(data_uuid)
            except Exception:
                detail = None
        if detail is None and document_id:
            try:
                detail = self.asforms_collate(document_id)
            except Exception:
                detail = None

        if not detail:
            return {"ok": False, "reason": "no_detail", "documentID": document_id, "dataUUID": data_uuid}

        # расплющим "data"
        flat = {}
        data_arr = detail["data"] if isinstance(detail, dict) and "data" in detail else []
        for it in data_arr:
            i = it.get("id")
            if not i: continue
            val = it.get("value")
            if val is None and "label" in it:
                val = it.get("label")
            flat[i] = val

        record = {
            "Статус": flat.get("listbox_status"),
            "Дата оформления": flat.get("date_registration"),
            "N": flat.get("textbox_number"),
            "Заявка": flat.get("reglink_application"),
            "Испытательная лаборатория": flat.get("reglink_testing_laboratory") or flat.get("textbox_applicant"),
            "БИН": flat.get("textbox_bin"),
            "Полное наименование": flat.get("textbox_full_name"),
            "Полное наименование на казахском": flat.get("textbox_full_name_kz"),
            "Сокращенное наименование": flat.get("textbox_short_name"),
            "Руководитель ИЛ": flat.get("textbox_manager_ilm"),
            "Юридический адрес": flat.get("textbox_legal_address"),
            "Юридический адрес (каз)": flat.get("textbox_legal_address_kz"),
            "Фактический адрес": flat.get("textbox_actual_address"),
            "VIN": flat.get("textbox_vin"),
            "Категория": flat.get("listbox_category"),
        }
        return {"ok": True, "record": record, "documentID": document_id, "dataUUID": data_uuid}


