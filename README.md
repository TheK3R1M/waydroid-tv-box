# Spike TV box: rebuild kit

Bu depo, bir evdeki TV kutusunu (Proxmox üzerinde headless Linux, HDMI ile TV'ye bağlı, Waydroid ile Android TV 13, canlı kanallar için host mpv, telefonlardan LAN web kumandası) sıfırdan kurmak için bir **beceri seti** (skill set) olarak hazırlanmıştır. Bir insan da, bir AI ajanı da aynı sırayla ilerleyerek kutuyu yeniden üretebilir.

> **Gövde dili Türkçe, başlıklar İngilizce.** Ajan için giriş noktası: [SKILL.md](SKILL.md). Adım adım kurulum: [docs/](docs/). Doğrulama listesi: [CHECKLIST.md](CHECKLIST.md).
>
> **Durum etiketleri:** ✅ = referans kutuda doğrulandı · ❔ = doğrulanmadı / kısmen doğrulandı · ⚠️ = tehlike.

## Ne işe yarar

- Proxmox VE 9.x (Debian 13) üzerinde headless bir TV kutusu: Weston kiosk (DRM), PipeWire/WirePlumber ses, Waydroid (Android TV 13, ARM çeviri katmanı).
- Canlı kanallar ve bölünmüş ekran host üzerinde mpv ile oynar; Android'in üstünde durur.
- Aile telefonları LAN'daki web kumandasını açar ("Ana ekrana ekle"). Fiziksel USB hava-faresi kumanda da canlı yayında çalışır ❔.
- Android LAN'dan izole edilir (internet açık); bir bot gibi davranan uygulamaları tv-guard karantinaya alır ❔.
- PC'den HDMI çıkışını izleme ve adb/scrcpy ile kontrol.

## Mimari

```
  Aile telefonları (Android, LAN)           Yönetici PC (Windows)
  ───────────────────────────               ─────────────────────
  http://<TV_HOST_IP>:8090                  adb / scrcpy (5555, yalnız PC'den DNAT)
  https://<TV_HOSTNAME> (isteğe bağlı)      ffplay "TV Ekran (HDMI)" (ssh → tv-hdmi-stream)
            │                                         │
            ▼                                         ▼
 ┌──────────────── Proxmox VE (Debian 13, host = root) ─────────────────────────────────┐
 │  tv-remote.py  (:8090 http, :443 https, stdlib)                                       │
 │     ├─ adb shell (kalıcı, onaylı komutlar) ─────────┐                                 │
 │     ├─ pactl (HDMI sink ses seviyesi)               │                                 │
 │     ├─ mpv IPC /run/tv/mpv-split.sock ──┐           │                                 │
 │     └─ evdev köprüsü: USB kumanda → aksiyonlar ◄────┼── (canlı yayın sırasında) ❔     │
 │                                          ▼          ▼                                 │
 │  tv-weston (kiosk-shell, DRM, DP-3 1920x1080)                                         │
 │     ├─ mpv (host; canlı kanal + bölünmüş ekran, Android'in üstünde)                   │
 │     └─ Waydroid Android TV 13 (tam ekran, ayrıcalıklı LXC, binder) ── waydroid0       │
 │                                                                  <waydroid0 subnet>     │
 │  tv-pipewire → tv-pipewire-pulse + tv-wireplumber → HDMI ses çıkışı                   │
 │  tv-net-isolate: Android → yalnız internet (RFC1918/CGNAT/link-local DROP)            │
 │     └─ tv-guard: TV-GUARD zinciri + dakikalık denetim ve karantina ❔                 │
 │  tv-android-heal (1 dk zamanlayıcı): "failed to attach" fırtınasında Android'i yeniden başlatır │
 │  logind: güç tuşu yok sayılır (uzaktan kumandanın güç tuşu kutuyu kapatmaz) ✅        │
 └────────────────────────────────────────────────────────────────────────────────────────┘
                       │ HDMI (DP-3)
                       ▼
                 Salon TV (CEC yok)
```

## Donanım (referans kutu)

| Ne | Değer |
|---|---|
| CPU | AMD Ryzen Embedded R2314 (Zen+, family 23 model 24), 4 çekirdek. **Android TV 16 açılmaz; ATV 13 kullanın.** |
| RAM | 13 GB |
| iGPU | AMD Raven2 (Vega), HDMI çıkışı DP-3 |
| WiFi | RTL8852BE (`rtw89`) = uplink. Kablolu NIC kullanılmıyor. |
| Depolama | 68 GB kök + 141 GB local-lvm |
| Diğer | Bir USB 2.4 GHz hava-faresi kumanda (CEC yoksa tek fiziksel kumanda seçeneği) |

Ayrıntı ve bilinen tuzaklar: [docs/02-hardware.md](docs/02-hardware.md).

## İki kurulum yolu

**(a) İnsan olarak:** [docs/](docs/) klasöründeki bölümleri sırayla izleyin: 01 → 16. Her aşamanın sonunda [CHECKLIST.md](CHECKLIST.md) ilgili bölümünü işaretleyin.

**(b) Bir AI ajanına vererek:** Depoyu ajana verin ve "önce SKILL.md'yi oku, sonra fazları sırayla uygula; her fazda doğrulama kapısını geçmeden ilerleme" deyin. Ajan kuralları [docs/13-agent-rules.md](docs/13-agent-rules.md) ve [SKILL.md](SKILL.md) içinde bulur.

## Yer tutucuları doldurma (placeholders)

Dosyalardaki `__TOKEN__` değerleri ev ağınıza özeldir. **Asla orijinal kitte doldurmayın.** Bir kopya alın:

```bash
cp -a tv-setup-kit tv-setup-kit-filled
TV_HOST_IP=192.168.10.5 ADMIN_PC_IP=192.168.10.9 LAN_CIDR=192.168.10.0/24 \
GATEWAY_IP=192.168.10.1 TV_HOSTNAME=tv.example.lan ANDROID_IP=<waydroid-ip> \
WIFI_SSID=<ssid> AIRPLAY_PIN=<4 digits> \
tools/fill-placeholders.sh tv-setup-kit-filled
```

`ANDROID_IP`, Waydroid'in `waydroid0` üzerindeki konteyner adresidir (`waydroid status` ile bakın, `192.168.240.x`).
`check-placeholders.sh` hâlâ `__TOKEN__` bulursa hata verir. Örnek adresler belgelemedir; kendi ağınızı kullanın.

## Depo düzeni

| Yol | İçerik |
|---|---|
| [SKILL.md](SKILL.md) | Ajan giriş noktası: fazlar, doğrulama kapıları, kurallar |
| [docs/](docs/) | Bölümler: 01 genel bakış … 13 ajan kuralları, 14 fiziksel kumanda, 15 tv-guard, 16 değişiklikler, A dosya listesi, B açık konular |
| [CHECKLIST.md](CHECKLIST.md) | Doğrulama listesi (çıktıyı gördüğünüzde işaretleyin) |
| `files/` | Hedef yollarını yansıtır (`cp -a files/. /`): `/etc`, `/usr/local/bin`, `/var/lib/waydroid` |
| `optional/` | Varsayılan olarak kurulmaz: AirPlay (UxPlay), salt-okunur tanı betiği |
| `pc/` | Windows yardımcıları: HDMI izleyici, scrcpy kısayolları, sertifika yenileme |
| `tools/` | Doldurma, yer tutucu kontrolü, gizlilik taraması, uzaktan kumanda dağıtımı, UI mock |

## Durum (özet)

Canlı kutu doğrulanmış çalışan bir sistemdir; bu kit onun sanitize edilmiş, yeniden üretilebilir hâlidir. Yeni bölümler (fiziksel kumanda köprüsü, tv-guard, Firefox, ARM çeviri) için ❔ işaretleri geçerlidir. Ayrıntı: [docs/16-changes-2026-11.md](docs/16-changes-2026-11.md) ve [docs/B-open-items.md](docs/B-open-items.md).

## Gizlilik ve güvenlik

- Depoda ev ağı adresi, cihaz listesi, MAC adresi, sertifika/özel anahtar, Wi-Fi parolası, token veya PIN **yoktur**. `tools/privacy-scan.sh` bunu commit öncesi kontrol eder.
- Korsan/akış-kazıyıcı uygulamalar belgelenmez ve kurulmaz.
- Bu kutu güvenilmeyen APK'ları çalıştırabilir. LAN izolasyonu bunu sınırlar, bir sanal makinenin yerini tutmaz ([docs/10-security.md](docs/10-security.md)).
- Herhangi bir dış erişim (DNS, port, sertifika) yalnızca sahibin açık onayıyla yapılır.

## Lisans

MIT. Bkz. [LICENSE](LICENSE). Bu depo bir uyarı olmaksızın "olduğu gibi" sunulur: ağ, TV ve uygulamalarınızda sorumluluk sizindir; kurulum yapmadan önce kendi donanımınızda ve ağınızda test edin. Üçüncü taraf uygulamaların hüküm ve lisansları geçerlidir.
