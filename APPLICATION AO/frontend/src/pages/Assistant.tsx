import { Bot, Check, Copy, Loader2, MessageSquarePlus, Mic, RefreshCw, Send, Square, Trash2, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { poserQuestion, syntheseVocale, transcrire } from "../api/assistant";
import { api } from "../api/client";
import type { ConversationDetail, ConversationResume, EtatAssistant, MessageAssistant, ProjetResume, SourceAssistant } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import TexteReponse from "../components/assistant/TexteReponse";
import EnTetePage from "../components/EnTetePage";
import { CLASSE_CHAMP } from "../components/Filtres";
import { formaterDate } from "../lib/format";
import { useEnregistreur } from "../lib/useEnregistreur";

const SUGGESTIONS = [
  "Rédige dans mon style un article de CCTP pour des fenêtres PVC oscillo-battantes.",
  "Quel prix médian pour une porte-fenêtre aluminium 2 vantaux ?",
  "Quelles normes et DTU je cite pour les menuiseries extérieures ?",
  "Quel est le délai de la garantie de parfait achèvement ?",
];
const CLE_LECTURE = "application-ao:assistant-lecture";
const LONGUEUR_MAX = 4000;

interface ReponseEnCours {
  question: string;
  etape: string;
  texte: string;
  sources: SourceAssistant[];
}

function lireLecture(): boolean {
  try {
    return window.localStorage.getItem(CLE_LECTURE) === "1";
  } catch {
    return false;
  }
}

export default function Assistant() {
  const { utilisateur } = useAuth();
  const [etat, setEtat] = useState<EtatAssistant | null>(null);
  const [conversations, setConversations] = useState<ConversationResume[] | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [projets, setProjets] = useState<ProjetResume[]>([]);
  const [projetNouvelle, setProjetNouvelle] = useState<number | null>(null);
  const [saisie, setSaisie] = useState("");
  const [enCours, setEnCours] = useState<ReponseEnCours | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [lectureAuto, setLectureAuto] = useState(lireLecture);
  const [annonce, setAnnonce] = useState("");
  const arret = useRef<AbortController | null>(null);
  const fil = useRef<HTMLDivElement>(null);
  const lecteur = useLecteur();
  const lectureAutoRef = useRef(lectureAuto);
  lectureAutoRef.current = lectureAuto;

  const chargerEtat = useCallback(() => api<EtatAssistant>("/assistant/etat").then(setEtat).catch(() => undefined), []);
  const chargerConversations = useCallback(
    () => api<ConversationResume[]>("/assistant/conversations").then(setConversations).catch((p: unknown) => setErreur(p instanceof Error ? p.message : "Erreur")),
    [],
  );

  useEffect(() => {
    if (!utilisateur?.est_administrateur) return;
    void chargerEtat();
    void chargerConversations();
    api<ProjetResume[]>("/projets").then(setProjets).catch(() => setProjets([]));
  }, [utilisateur, chargerEtat, chargerConversations]);

  // Suivi de l'indexation tant qu'elle tourne.
  useEffect(() => {
    if (!etat?.index.en_cours) return;
    const minuteur = window.setInterval(() => void chargerEtat(), 3000);
    return () => window.clearInterval(minuteur);
  }, [etat?.index.en_cours, chargerEtat]);

  useEffect(() => {
    fil.current?.scrollTo({ top: fil.current.scrollHeight });
  }, [detail?.messages.length, enCours?.texte, enCours?.sources.length]);

  useEffect(() => () => arret.current?.abort(), []);

  if (!utilisateur?.est_administrateur) {
    return <p className="rounded-lg border border-bordure bg-surface px-4 py-3 text-attenue">L'assistant est réservé à l'administrateur.</p>;
  }

  async function ouvrir(id: number) {
    if (enCours) return;
    setErreur(null);
    lecteur.arreter();
    try {
      setDetail(await api<ConversationDetail>(`/assistant/conversations/${id}`));
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Conversation introuvable.");
    }
  }

  function nouvelle() {
    if (enCours) return;
    lecteur.arreter();
    setDetail(null);
    setErreur(null);
    setSaisie("");
  }

  async function supprimer(conversation: ConversationResume) {
    if (!window.confirm(`Supprimer la conversation « ${conversation.titre} » ?`)) return;
    try {
      await api(`/assistant/conversations/${conversation.id}`, { method: "DELETE" });
      if (detail?.id === conversation.id) setDetail(null);
      void chargerConversations();
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Suppression impossible.");
    }
  }

  async function changerProjet(valeur: string) {
    const projetId = valeur ? Number(valeur) : null;
    if (!detail) {
      setProjetNouvelle(projetId);
      return;
    }
    try {
      setDetail(await api<ConversationDetail>(`/assistant/conversations/${detail.id}`, { method: "PATCH", body: JSON.stringify({ projet_id: projetId }) }));
      void chargerConversations();
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Modification impossible.");
    }
  }

  async function envoyer(question: string) {
    const texte = question.trim();
    if (!texte || enCours) return;
    if (texte.length > LONGUEUR_MAX) {
      setErreur(`Votre question fait ${texte.length.toLocaleString("fr-FR")} caractères : ${LONGUEUR_MAX.toLocaleString("fr-FR")} au maximum. Raccourcissez-la ou envoyez-la en plusieurs fois.`);
      return;
    }
    setErreur(null);
    setAnnonce("");
    lecteur.arreter();
    let conversation = detail;
    let creee = false;
    try {
      if (!conversation) {
        conversation = await api<ConversationDetail>("/assistant/conversations", { method: "POST", body: JSON.stringify({ projet_id: projetNouvelle }) });
        creee = true;
        setDetail(conversation);
      }
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Conversation impossible.");
      return;
    }
    const identifiant = conversation.id;
    const controleur = new AbortController();
    arret.current = controleur;
    let reponse = "";
    let sourcesRecues: SourceAssistant[] = [];
    let recu = false;
    let terminee = false;
    let messageId: number | null = null;
    let supprimee = false;
    setSaisie("");
    setEnCours({ question: texte, etape: "Envoi…", texte: "", sources: [] });
    try {
      await poserQuestion(
        identifiant,
        texte,
        (evenement) => {
          recu = true;
          if (evenement.type === "etape") setEnCours((e) => (e ? { ...e, etape: evenement.texte } : e));
          else if (evenement.type === "sources") {
            sourcesRecues = evenement.sources;
            setEnCours((e) => (e ? { ...e, sources: evenement.sources } : e));
          } else if (evenement.type === "texte") {
            reponse += evenement.texte;
            setEnCours((e) => (e ? { ...e, texte: e.texte + evenement.texte } : e));
          } else if (evenement.type === "erreur") {
            setErreur(evenement.message);
            setAnnonce(evenement.message);
          } else if (evenement.type === "fin") {
            terminee = true;
            messageId = evenement.message_id;
          }
        },
        controleur.signal,
      );
    } catch (probleme) {
      if (!(probleme instanceof DOMException && probleme.name === "AbortError")) {
        setErreur(probleme instanceof Error ? probleme.message : "L'assistant ne répond pas.");
        if (!recu) {
          // Rien n'est parti : la question revient dans la zone de saisie.
          setSaisie(texte);
          if (creee) {
            supprimee = true;
            await api(`/assistant/conversations/${identifiant}`, { method: "DELETE" }).catch(() => undefined);
          }
        }
      }
    } finally {
      arret.current = null;
      const interrompue = controleur.signal.aborted;
      if (supprimee) {
        setDetail(null);
      } else {
        try {
          let relue = await api<ConversationDetail>(`/assistant/conversations/${identifiant}`);
          // Après « Arrêter », le serveur enregistre le début de réponse un instant plus tard.
          for (let essai = 0; interrompue && reponse && relue.messages.at(-1)?.role !== "assistant" && essai < 10; essai++) {
            await new Promise((r) => setTimeout(r, 300));
            relue = await api<ConversationDetail>(`/assistant/conversations/${identifiant}`);
          }
          if (interrompue && reponse && relue.messages.at(-1)?.role !== "assistant") {
            relue = {
              ...relue,
              messages: [...relue.messages, { id: -1, role: "assistant", texte: reponse, sources: sourcesRecues, interrompu: true, cree_le: "" }],
            };
          }
          setDetail(relue);
        } catch {
          // Conversation supprimée entre-temps : rien à relire.
        }
      }
      setEnCours(null);
      void chargerConversations();
      if (terminee) {
        setAnnonce("Réponse de l'assistant terminée.");
        if (lectureAutoRef.current && reponse) void lecteur.lire(messageId ?? -1, reponse);
      } else if (interrompue) {
        setAnnonce("Réponse interrompue.");
      }
    }
  }

  function basculerLecture() {
    const suivant = !lectureAuto;
    setLectureAuto(suivant);
    if (!suivant) lecteur.arreter();
    try {
      window.localStorage.setItem(CLE_LECTURE, suivant ? "1" : "0");
    } catch {
      // Préférence non mémorisée : sans conséquence.
    }
  }

  const pret = Boolean(etat?.moteur.joignable && etat.moteur.modele_installe && etat.moteur.embedding_installe);
  const messages = detail?.messages ?? [];

  return (
    <>
      <EnTetePage
        surtitre="Administrateur · IA locale et gratuite"
        titre="Assistant"
        sousTitre="Il répond à partir de vos documents, de vos prix et des modèles de pièces vérifiés. Tout reste sur votre poste : rien n'est envoyé sur Internet."
        actions={
          etat?.moteur.joignable ? (
            <button
              type="button"
              onClick={() => void api("/assistant/indexer", { method: "POST" }).then(chargerEtat)}
              disabled={etat.index.en_cours}
              className="flex min-h-11 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-sm font-semibold hover:bg-surface-2 disabled:opacity-50"
            >
              <RefreshCw aria-hidden="true" className={`size-4 ${etat.index.en_cours ? "animate-spin" : ""}`} />
              {etat.index.en_cours ? "Lecture des documents…" : "Relire mes documents"}
            </button>
          ) : undefined
        }
      />
      <span className="sr-only" aria-live="polite">
        {annonce}
      </span>

      {etat && <PanneauEtat etat={etat} />}

      <div className="flex flex-wrap items-start gap-4">
        <aside aria-label="Conversations" className="flex min-w-0 flex-[1_1_240px] flex-col gap-2 rounded-xl border border-bordure bg-surface p-3 lg:max-w-[300px]">
          <button
            type="button"
            onClick={nouvelle}
            disabled={Boolean(enCours)}
            className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-accent px-3 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
          >
            <MessageSquarePlus aria-hidden="true" className="size-4" />
            Nouvelle conversation
          </button>
          {conversations && conversations.length === 0 && <p className="px-1 py-2 text-xs text-attenue">Aucune conversation pour l'instant.</p>}
          <ul className="flex max-h-[60vh] flex-col gap-1 overflow-y-auto">
            {conversations?.map((c) => (
              <li key={c.id} className="group flex items-stretch gap-1">
                <button
                  type="button"
                  onClick={() => void ouvrir(c.id)}
                  aria-current={detail?.id === c.id ? "true" : undefined}
                  className={`flex min-h-11 min-w-0 flex-1 flex-col justify-center rounded-lg px-2.5 py-1.5 text-left ${
                    detail?.id === c.id ? "bg-surface-2 text-white" : "text-attenue hover:bg-surface-2 hover:text-texte"
                  }`}
                >
                  <span className="truncate text-sm font-medium">{c.titre}</span>
                  <span className="truncate text-[11px] text-attenue">
                    {c.projet ? `${c.projet.nom} · ` : ""}
                    {formaterDate(c.modifie_le)}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => void supprimer(c)}
                  disabled={Boolean(enCours)}
                  aria-label={`Supprimer la conversation « ${c.titre} »`}
                  className="grid w-9 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger disabled:opacity-40"
                >
                  <Trash2 aria-hidden="true" className="size-4" />
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section aria-label="Discussion" className="flex min-w-0 flex-[999_1_560px] flex-col rounded-xl border border-bordure bg-surface">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-bordure px-4 py-3">
            <h2 className="min-w-0 flex-[1_1_200px] truncate font-titre text-base font-semibold">{detail?.titre ?? "Nouvelle conversation"}</h2>
            <label className="flex min-w-0 items-center gap-2 text-xs text-attenue">
              Projet
              <select
                value={String(detail ? (detail.projet?.id ?? "") : (projetNouvelle ?? ""))}
                onChange={(e) => void changerProjet(e.target.value)}
                disabled={Boolean(enCours)}
                className="h-10 max-w-56 rounded-lg border border-bordure-forte bg-fond px-2 text-sm text-texte"
              >
                <option value="">Aucun</option>
                {projets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.nom}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={basculerLecture}
              aria-pressed={lectureAuto}
              className={`flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm ${
                lectureAuto ? "border-accent/60 bg-accent/10 text-accent" : "border-bordure-forte text-attenue hover:bg-surface-2"
              }`}
            >
              {lectureAuto ? <Volume2 aria-hidden="true" className="size-4" /> : <VolumeX aria-hidden="true" className="size-4" />}
              Réponses à voix haute
            </button>
          </div>

          <div ref={fil} className="flex max-h-[62vh] min-h-[320px] flex-col gap-4 overflow-y-auto px-4 py-4">
            {messages.length === 0 && !enCours && (
              <div className="flex flex-col items-start gap-3 py-6">
                <p className="text-attenue">Posez une question par écrit ou au micro. Exemples :</p>
                <div className="flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => void envoyer(s)}
                      disabled={!pret}
                      className="rounded-full border border-bordure-forte px-3 py-1.5 text-left text-sm text-texte hover:border-accent/60 hover:bg-accent/10 disabled:opacity-50"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) =>
              m.role === "user" ? (
                <BulleQuestion key={m.id} texte={m.texte} />
              ) : (
                <BulleReponse
                  key={m.id}
                  message={m}
                  enLecture={lecteur.enLecture === m.id}
                  chargementLecture={lecteur.chargement === m.id}
                  surLecture={() => (lecteur.enLecture === m.id ? lecteur.arreter() : void lecteur.lire(m.id, m.texte))}
                  voixDisponible={Boolean(etat?.voix.synthese_installee)}
                />
              ),
            )}
            {enCours && (
              <>
                <BulleQuestion texte={enCours.question} />
                <BulleReponse
                  message={{ id: 0, role: "assistant", texte: enCours.texte, sources: enCours.sources, interrompu: false, cree_le: "" }}
                  etape={enCours.texte ? undefined : enCours.etape}
                />
              </>
            )}
          </div>

          {erreur && (
            <p role="alert" className="mx-4 mb-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
              {erreur}
            </p>
          )}
          <Saisie
            valeur={saisie}
            surChangement={setSaisie}
            surEnvoi={(texte) => void envoyer(texte)}
            enCours={Boolean(enCours)}
            surArret={() => arret.current?.abort()}
            desactive={!pret}
            micro={Boolean(etat?.voix.transcription_installee)}
            envoiAutomatique={lectureAuto}
            surErreur={setErreur}
          />
        </section>
      </div>
    </>
  );
}

function BulleQuestion({ texte }: { texte: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 whitespace-pre-wrap">{texte}</p>
    </div>
  );
}

function BulleReponse({
  message,
  etape,
  enLecture = false,
  chargementLecture = false,
  surLecture,
  voixDisponible = false,
}: {
  message: MessageAssistant;
  etape?: string;
  enLecture?: boolean;
  chargementLecture?: boolean;
  surLecture?: () => void;
  voixDisponible?: boolean;
}) {
  const [copie, setCopie] = useState(false);
  const [surbrillance, setSurbrillance] = useState<number | null>(null);
  const sources = useRef<HTMLDetailsElement>(null);

  function montrerSource(numero: number) {
    setSurbrillance(numero);
    if (sources.current) sources.current.open = true;
    sources.current?.querySelector(`[data-source="${numero}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    window.setTimeout(() => setSurbrillance(null), 2000);
  }

  async function copier() {
    try {
      await navigator.clipboard.writeText(message.texte.replace(/\s*\[\d+(?:\s*[,;–-]\s*\d+)*\]/g, ""));
      setCopie(true);
      window.setTimeout(() => setCopie(false), 1500);
    } catch {
      setCopie(false);
    }
  }

  return (
    <div className="flex gap-3">
      <span aria-hidden="true" className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-accent/15 text-accent">
        <Bot className="size-4.5" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        {etape ? (
          <p className="flex items-center gap-2 text-attenue">
            <Loader2 aria-hidden="true" className="size-4 animate-spin" />
            {etape}
          </p>
        ) : (
          <div className="leading-relaxed">
            <TexteReponse texte={message.texte} surRenvoi={montrerSource} />
            {message.interrompu && <p className="mt-1 text-xs text-attenue">Réponse interrompue.</p>}
          </div>
        )}
        {message.sources.length > 0 && (
          <details ref={sources} className="rounded-lg border border-bordure bg-fond/40">
            <summary className="min-h-9 cursor-pointer px-3 py-2 text-xs font-semibold text-attenue">
              {message.sources.length} source{message.sources.length > 1 ? "s" : ""} consultée{message.sources.length > 1 ? "s" : ""}
            </summary>
            <ol className="flex flex-col gap-1 px-3 pb-2">
              {message.sources.map((s) => (
                <li
                  key={s.numero}
                  data-source={s.numero}
                  className={`flex gap-2 rounded-md px-1.5 py-1 text-xs transition-colors ${surbrillance === s.numero ? "bg-accent/15" : ""}`}
                >
                  <span className="font-bold text-accent">{s.numero}</span>
                  <span className="min-w-0">
                    {s.lien ? (
                      <a href={s.lien} target="_blank" rel="noopener" className="font-semibold text-texte">
                        {s.titre}
                      </a>
                    ) : (
                      <span className="font-semibold">{s.titre}</span>
                    )}
                    <span className="block text-attenue">{s.detail}</span>
                  </span>
                </li>
              ))}
            </ol>
          </details>
        )}
        {message.id > 0 && (
          <div className="flex gap-1">
            {voixDisponible && (
              <button
                type="button"
                onClick={surLecture}
                aria-pressed={enLecture}
                className="flex min-h-9 items-center gap-1.5 rounded-lg px-2.5 text-xs text-attenue hover:bg-surface-2 hover:text-texte"
              >
                {chargementLecture ? <Loader2 aria-hidden="true" className="size-3.5 animate-spin" /> : <Volume2 aria-hidden="true" className="size-3.5" />}
                {enLecture ? "Arrêter la lecture" : "Écouter"}
              </button>
            )}
            <button type="button" onClick={() => void copier()} className="flex min-h-9 items-center gap-1.5 rounded-lg px-2.5 text-xs text-attenue hover:bg-surface-2 hover:text-texte">
              {copie ? <Check aria-hidden="true" className="size-3.5" /> : <Copy aria-hidden="true" className="size-3.5" />}
              {copie ? "Copié" : "Copier"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function Saisie({
  valeur,
  surChangement,
  surEnvoi,
  enCours,
  surArret,
  desactive,
  micro,
  envoiAutomatique,
  surErreur,
}: {
  valeur: string;
  surChangement: (valeur: string) => void;
  surEnvoi: (texte: string) => void;
  enCours: boolean;
  surArret: () => void;
  desactive: boolean;
  micro: boolean;
  envoiAutomatique: boolean;
  surErreur: (message: string | null) => void;
}) {
  const enregistreur = useEnregistreur();
  const [transcription, setTranscription] = useState(false);
  const { enregistre, annuler } = enregistreur;

  // Question envoyée autrement (clavier, suggestion) pendant une dictée : le micro est coupé.
  useEffect(() => {
    if (enCours && enregistre) annuler();
  }, [enCours, enregistre, annuler]);

  function soumettre(evenement: FormEvent) {
    evenement.preventDefault();
    surEnvoi(valeur);
  }

  function clavier(evenement: KeyboardEvent<HTMLTextAreaElement>) {
    if (evenement.key === "Enter" && !evenement.shiftKey && !evenement.nativeEvent.isComposing) {
      evenement.preventDefault();
      surEnvoi(valeur);
    }
  }

  async function basculerMicro() {
    surErreur(null);
    if (!enregistreur.enregistre) {
      try {
        await enregistreur.demarrer();
      } catch (probleme) {
        surErreur(
          probleme instanceof DOMException && probleme.name === "NotAllowedError"
            ? "Accès au micro refusé : autorisez-le dans le navigateur (icône à gauche de l'adresse)."
            : probleme instanceof Error
              ? probleme.message
              : "Micro indisponible.",
        );
      }
      return;
    }
    const audio = await enregistreur.arreter();
    if (!audio) return;
    setTranscription(true);
    try {
      const texte = (await transcrire(audio)).trim();
      if (!texte) {
        surErreur("Je n'ai rien entendu. Rapprochez-vous du micro et réessayez.");
      } else if (envoiAutomatique) {
        surEnvoi(texte);
      } else {
        surChangement(valeur ? `${valeur.trimEnd()} ${texte}` : texte);
      }
    } catch (probleme) {
      surErreur(probleme instanceof Error ? probleme.message : "Transcription impossible.");
    } finally {
      setTranscription(false);
    }
  }

  const minutes = `${Math.floor(enregistreur.duree / 60)}:${String(enregistreur.duree % 60).padStart(2, "0")}`;
  return (
    <form onSubmit={soumettre} className="flex items-end gap-2 border-t border-bordure p-3">
      <label htmlFor="question-assistant" className="sr-only">
        Votre question
      </label>
      <textarea
        id="question-assistant"
        value={valeur}
        onChange={(e) => surChangement(e.target.value)}
        onKeyDown={clavier}
        rows={Math.min(6, Math.max(1, valeur.split("\n").length))}
        placeholder={desactive ? "L'assistant n'est pas encore prêt (voir ci-dessus)." : enregistreur.enregistre ? "Je vous écoute…" : "Votre question… (Entrée pour envoyer, Maj+Entrée pour aller à la ligne)"}
        disabled={desactive}
        maxLength={LONGUEUR_MAX}
        aria-describedby={valeur.length > LONGUEUR_MAX * 0.8 ? "compteur-question" : undefined}
        className={`${CLASSE_CHAMP} min-h-11 flex-1 resize-none py-2.5 leading-snug`}
      />
      {valeur.length > LONGUEUR_MAX * 0.8 && (
        <span id="compteur-question" className="self-center text-xs whitespace-nowrap text-attenue">
          {valeur.length.toLocaleString("fr-FR")} / {LONGUEUR_MAX.toLocaleString("fr-FR")}
        </span>
      )}
      {micro && (
        <button
          type="button"
          onClick={() => void basculerMicro()}
          disabled={!enregistreur.enregistre && (desactive || enCours || transcription || enregistreur.ouverture)}
          aria-pressed={enregistreur.enregistre}
          aria-label={
            enregistreur.enregistre ? "Arrêter l'enregistrement et transcrire" : enregistreur.ouverture ? "Ouverture du micro…" : "Dicter la question au micro"
          }
          className={`flex min-h-11 items-center gap-2 rounded-lg border px-3 font-semibold disabled:opacity-50 ${
            enregistreur.enregistre ? "animate-pulse border-danger/70 bg-danger/15 text-danger" : "border-bordure-forte text-texte hover:bg-surface-2"
          }`}
        >
          {transcription ? <Loader2 aria-hidden="true" className="size-4.5 animate-spin" /> : enregistreur.enregistre ? <Square aria-hidden="true" className="size-4" /> : <Mic aria-hidden="true" className="size-4.5" />}
          {enregistreur.enregistre ? minutes : transcription ? "Transcription…" : null}
        </button>
      )}
      {enCours ? (
        <button type="button" onClick={surArret} className="flex min-h-11 items-center gap-2 rounded-lg border border-bordure-forte px-3 font-semibold hover:bg-surface-2">
          <Square aria-hidden="true" className="size-4" />
          Arrêter
        </button>
      ) : (
        <button
          type="submit"
          disabled={desactive || !valeur.trim()}
          aria-label="Envoyer la question"
          className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
        >
          <Send aria-hidden="true" className="size-4" />
        </button>
      )}
    </form>
  );
}

function PanneauEtat({ etat }: { etat: EtatAssistant }) {
  const { moteur, index, voix } = etat;
  let probleme: string | null = null;
  if (!moteur.joignable) probleme = "Le moteur d'IA (Ollama) ne répond pas. Relancez installer.ps1, ou démarrez l'application avec « docker compose up -d ».";
  else if (!moteur.modele_installe || !moteur.embedding_installe)
    probleme = `Les modèles d'IA ne sont pas encore téléchargés (${[!moteur.modele_installe && moteur.modele, !moteur.embedding_installe && moteur.embedding].filter(Boolean).join(", ")}). Relancez installer.ps1 : il les télécharge une fois pour toutes (environ 8 Go).`;

  const aIndexer = index.passages - index.a_jour;
  const voixManquante = !voix.transcription_installee || !voix.synthese_installee;
  const messageIndex = index.message && index.message !== "Index à jour." ? index.message : "";
  if (!probleme && !index.en_cours && aIndexer === 0 && index.passages > 0 && !voixManquante && !messageIndex) return null;

  return (
    <section aria-label="État de l'assistant" className="flex flex-col gap-1.5 rounded-xl border border-bordure bg-surface px-4 py-3">
      {probleme ? (
        <p role="alert" className="text-danger">
          {probleme}
        </p>
      ) : index.en_cours ? (
        <>
          <p>
            <strong className="text-accent">Lecture de vos documents par l'IA…</strong> {index.faits} / {index.total}. L'assistant répond déjà avec ce qui est lu.
          </p>
          <div className="h-1.5 overflow-hidden rounded-full bg-fond" role="progressbar" aria-valuemin={0} aria-valuemax={index.total || 1} aria-valuenow={index.faits} aria-label="Lecture des documents">
            <div className="h-full bg-accent transition-all" style={{ width: `${index.total ? (100 * index.faits) / index.total : 5}%` }} />
          </div>
        </>
      ) : (
        <p className="text-attenue">
          {aIndexer > 0 || index.passages === 0 ? `${aIndexer || "Aucun"} élément${aIndexer > 1 ? "s" : ""} de vos documents à faire lire par l'IA (bouton « Relire mes documents »). ` : ""}
          {messageIndex}
          {voixManquante ? " La voix n'est pas encore installée : relancez installer.ps1." : ""}
        </p>
      )}
    </section>
  );
}

/** Lecture à voix haute d'une réponse (une seule à la fois). */
function useLecteur() {
  const [enLecture, setEnLecture] = useState<number | null>(null);
  const [chargement, setChargement] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const requete = useRef<AbortController | null>(null);

  const arreter = useCallback(() => {
    requete.current?.abort();
    requete.current = null;
    if (audio.current) {
      audio.current.pause();
      URL.revokeObjectURL(audio.current.src);
      audio.current = null;
    }
    setEnLecture(null);
    setChargement(null);
  }, []);

  useEffect(() => arreter, [arreter]);

  const lire = useCallback(
    async (id: number, texte: string) => {
      arreter();
      const controleur = new AbortController();
      requete.current = controleur;
      setChargement(id);
      try {
        const son = await syntheseVocale(texte, controleur.signal);
        const element = new Audio(URL.createObjectURL(son));
        audio.current = element;
        element.onended = () => arreter();
        setEnLecture(id);
        await element.play();
      } catch {
        if (!controleur.signal.aborted) arreter();
      } finally {
        setChargement((c) => (c === id ? null : c));
      }
    },
    [arreter],
  );

  return { enLecture, chargement, lire, arreter };
}
