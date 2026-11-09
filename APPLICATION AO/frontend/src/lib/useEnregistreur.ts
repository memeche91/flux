import { useCallback, useEffect, useRef, useState } from "react";

/** Enregistrement du micro (MediaRecorder) : renvoie l'audio à l'arrêt. */
export function useEnregistreur() {
  const [enregistre, setEnregistre] = useState(false);
  const [ouverture, setOuverture] = useState(false);
  const [duree, setDuree] = useState(0);
  const enregistreur = useRef<MediaRecorder | null>(null);
  const resolution = useRef<((audio: Blob | null) => void) | null>(null);
  const minuteur = useRef<number | null>(null);
  const demarrage = useRef(false);
  const monte = useRef(true);

  const liberer = useCallback(() => {
    enregistreur.current?.stream.getTracks().forEach((piste) => piste.stop());
    enregistreur.current = null;
    if (minuteur.current !== null) window.clearInterval(minuteur.current);
    minuteur.current = null;
    if (monte.current) setEnregistre(false);
  }, []);

  useEffect(() => {
    monte.current = true;
    return () => {
      monte.current = false;
      resolution.current = null;
      liberer();
    };
  }, [liberer]);

  const demarrer = useCallback(async () => {
    // Un seul démarrage à la fois : un double clic pendant la demande d'autorisation est ignoré.
    if (demarrage.current || enregistreur.current) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      throw new Error("Ce navigateur ne permet pas d'enregistrer le micro.");
    }
    demarrage.current = true;
    setOuverture(true);
    let flux: MediaStream;
    try {
      flux = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } finally {
      demarrage.current = false;
      if (monte.current) setOuverture(false);
    }
    if (!monte.current) {
      flux.getTracks().forEach((piste) => piste.stop());
      return;
    }
    const type = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
    const nouvel = new MediaRecorder(flux, type ? { mimeType: type } : undefined);
    const morceaux: Blob[] = [];
    nouvel.ondataavailable = (evenement) => {
      if (evenement.data.size) morceaux.push(evenement.data);
    };
    nouvel.onstop = () => {
      const audio = morceaux.length ? new Blob(morceaux, { type: nouvel.mimeType || "audio/webm" }) : null;
      liberer();
      resolution.current?.(audio);
      resolution.current = null;
    };
    enregistreur.current = nouvel;
    nouvel.start(250);
    setDuree(0);
    setEnregistre(true);
    const debut = Date.now();
    minuteur.current = window.setInterval(() => setDuree(Math.floor((Date.now() - debut) / 1000)), 250);
  }, [liberer]);

  const arreter = useCallback(
    () =>
      new Promise<Blob | null>((resoudre) => {
        if (!enregistreur.current || enregistreur.current.state === "inactive") {
          resoudre(null);
          return;
        }
        resolution.current = resoudre;
        enregistreur.current.stop();
      }),
    [],
  );

  /** Coupe le micro sans rien transcrire. */
  const annuler = useCallback(() => {
    resolution.current = null;
    if (enregistreur.current && enregistreur.current.state !== "inactive") {
      enregistreur.current.onstop = () => liberer();
      enregistreur.current.stop();
    } else {
      liberer();
    }
  }, [liberer]);

  return { enregistre, ouverture, duree, demarrer, arreter, annuler };
}
