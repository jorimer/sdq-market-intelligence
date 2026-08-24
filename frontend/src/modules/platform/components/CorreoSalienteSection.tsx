import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Mail, Loader2, CheckCircle2, AlertTriangle, Send } from "lucide-react";
import { Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { settingsApi, type SmtpSettings } from "../settingsApi";
import { mensajeDeError } from "@/shared/api/errores";

/**
 * Correo saliente. Admin-only (la página lo gatea).
 *
 * Existe porque el canal `email` de las alertas estaba implementado y era inalcanzable: se
 * encendía con variables de entorno, o sea con acceso al panel de infraestructura y un
 * redeploy. La llave de Claude se configura acá desde siempre; tener dos llaveros para la
 * misma clase de secreto es cómo se llega a «pensé que estaba puesto».
 *
 * Tres decisiones de comportamiento:
 *
 * 1. **El veredicto lo trae el backend** (`configurado` + `falta`), no se deduce acá. Si la
 *    pantalla dedujera «hay host ⇒ hay canal», el día que el emisor agregue una condición
 *    seguiría diciendo que sí.
 * 2. **La contraseña se muestra como estado, nunca como valor.** El campo va vacío con un
 *    aviso de que hay una guardada; dejarlo vacío al guardar la CONSERVA.
 * 3. **Probar manda un correo de verdad.** Un botón que valide el formulario y diga «listo»
 *    responde una pregunta distinta —y más fácil— que la que el admin está haciendo.
 */
const VACIO: SmtpSettings = {
  host: "", port: 587, user: "", fromAddress: "", starttls: true,
  passwordSet: false, configurado: false, falta: [],
};

export function CorreoSalienteSection() {
  const { t } = useTranslation();
  const tr = (k: string, d: string) => t(k, d) as string;
  const [smtp, setSmtp] = useState<SmtpSettings>(VACIO);
  const [password, setPassword] = useState("");
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [probando, setProbando] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState(false);
  const [prueba, setPrueba] = useState<{ ok: boolean; detalle: string } | null>(null);

  async function recargar() {
    setCargando(true);
    setError("");
    try {
      const s = await settingsApi.get();
      setSmtp(s.smtp ?? VACIO);
    } catch (e) {
      setError(mensajeDeError(e, tr("platform.smtp.loadError",
        "No se pudo leer la configuración de correo.")));
    } finally {
      setCargando(false);
    }
  }

  useEffect(() => { recargar(); }, []);

  async function guardar() {
    setGuardando(true);
    setError(""); setOk(false); setPrueba(null);
    try {
      const s = await settingsApi.update({
        smtp: {
          host: smtp.host, port: smtp.port, user: smtp.user,
          fromAddress: smtp.fromAddress, starttls: smtp.starttls,
          // Vacío = no la toques. Es lo que evita que cambiar el remitente borre la llave.
          ...(password ? { password } : {}),
        },
      });
      setSmtp(s.smtp ?? VACIO);
      setPassword("");
      setOk(true);
    } catch (e) {
      setError(mensajeDeError(e, tr("platform.smtp.saveError",
        "No se pudo guardar la configuración.")));
    } finally {
      setGuardando(false);
    }
  }

  async function probar() {
    setProbando(true);
    setPrueba(null);
    try {
      const r = await settingsApi.testSmtp();
      setPrueba({
        ok: r.status === "success",
        detalle: r.status === "success"
          ? tr("platform.smtp.testOk", "Correo enviado a {{to}}. Revisá tu bandeja.")
              .replace("{{to}}", r.destinatario)
          : r.detail,
      });
    } catch (e) {
      setPrueba({ ok: false, detalle: mensajeDeError(e,
        tr("platform.smtp.testError", "No se pudo probar el envío.")) });
    } finally {
      setProbando(false);
    }
  }

  const campo = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm";

  return (
    <Card>
      <CardHead
        icon={Mail}
        title={tr("platform.smtp.title", "Correo saliente")}
        subtitle={tr("platform.smtp.sub",
          "Por dónde salen los avisos de las vigilancias. Sin esto, el canal «correo» no se ofrece.")}
      />
      <div className="p-4 space-y-4">
        {cargando ? (
          <StateBlock kind="loading" message={tr("common.loading", "Cargando…")} />
        ) : (
          <>
            {/* El estado va ARRIBA: es lo que el admin vino a saber. */}
            <div className={`flex items-start gap-2 text-sm ${smtp.configurado ? "text-ok" : "text-warn"}`}>
              {smtp.configurado ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
                                : <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />}
              <span>
                {smtp.configurado
                  ? tr("platform.smtp.on", "El canal de correo está activo.")
                  : tr("platform.smtp.off", "El canal de correo NO está activo, así que no se ofrece en las vigilancias.")}
                {smtp.falta.length > 0 && (
                  <span className="text-muted">
                    {" "}{tr("platform.smtp.missing", "Falta:")} {smtp.falta.join(" · ")}
                  </span>
                )}
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-xs text-muted">{tr("platform.smtp.host", "Servidor (host)")}</span>
                <input className={campo} value={smtp.host} placeholder="smtp.resend.com"
                       onChange={(e) => setSmtp({ ...smtp, host: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs text-muted">{tr("platform.smtp.port", "Puerto")}</span>
                <input className={campo} type="number" value={smtp.port}
                       onChange={(e) => setSmtp({ ...smtp, port: Number(e.target.value) || 587 })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs text-muted">{tr("platform.smtp.user", "Usuario")}</span>
                <input className={campo} value={smtp.user} placeholder="resend"
                       onChange={(e) => setSmtp({ ...smtp, user: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs text-muted">
                  {tr("platform.smtp.password", "Contraseña o llave de API")}
                </span>
                <input className={campo} type="password" value={password}
                       autoComplete="new-password"
                       placeholder={smtp.passwordSet
                         ? tr("platform.smtp.passwordSet", "Hay una guardada — dejalo vacío para conservarla")
                         : ""}
                       onChange={(e) => setPassword(e.target.value)} />
              </label>
              <label className="space-y-1 sm:col-span-2">
                <span className="text-xs text-muted">
                  {tr("platform.smtp.from", "Remitente («De»)")}
                </span>
                <input className={campo} value={smtp.fromAddress}
                       placeholder="SDQ·MIP <alertas@sdqconsulting.com.do>"
                       onChange={(e) => setSmtp({ ...smtp, fromAddress: e.target.value })} />
              </label>
              <label className="flex items-center gap-2 sm:col-span-2 text-sm">
                <input type="checkbox" checked={smtp.starttls}
                       onChange={(e) => setSmtp({ ...smtp, starttls: e.target.checked })} />
                <span>{tr("platform.smtp.starttls", "Usar STARTTLS (recomendado en el puerto 587)")}</span>
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button onClick={guardar} disabled={guardando} className="btn btn-primary text-sm">
                {guardando && <Loader2 className="w-4 h-4 animate-spin" />}
                {tr("common.save", "Guardar")}
              </button>
              {/* Probar sólo tiene sentido con el canal encendido; ofrecerlo apagado es
                  ofrecer un botón cuya única respuesta posible es «falta el host». */}
              <button onClick={probar} disabled={probando || !smtp.configurado}
                      className="btn btn-ghost text-sm disabled:opacity-40"
                      title={smtp.configurado ? "" : tr("platform.smtp.testDisabled",
                        "Configurá y guardá el servidor primero.")}>
                {probando ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                {tr("platform.smtp.test", "Enviar correo de prueba")}
              </button>
              {ok && <span className="text-xs text-ok">{tr("common.saved", "Guardado.")}</span>}
            </div>

            {error && <StateBlock kind="error" message={error} />}
            {prueba && (
              <div className={`text-xs ${prueba.ok ? "text-ok" : "text-alert"}`}>
                {prueba.detalle}
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
