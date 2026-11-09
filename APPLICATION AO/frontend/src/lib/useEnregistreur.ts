import { useCallback, useEffect, useRef, useState } from "react";

/** Enregistrement du micro (MediaRecorder) : renvoie l'audio à l'arrêt. */
export function useEnregistreur() {
  const [enregistre, setEnregistre] = useState(false);
  const [duree, setDuree] = useState(0);
  const enregistreur = useRef<MediaRecorder | null>(null);
  const morceaux = useRef<Blob[]>([]);
  const resolution = useRef<((audio: Blob | null) => void) | null>(null);
  const minuteur = useRef<number | null>(null);

  const liberer = useCallback(() => {
    enregistreur.current?.stream.getTracks().forEach((piste) => piste.stop());
    enregistreur.current = null;
    if (minuteur.current !== null) window.clearInterval(minuteur.current);
    minuteur.current = null;
    setEnregistre(false);
  }, []);

  useEffect(() => liberer, [liberer]);

  const demarrer = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      throw new Error("Ce navigateur ne permet pas d'enregistrer le micro.");
    }
    const flux = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const type = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
    const nouvel = new MediaRecorder(flux, type ? { mimeType: type } : undefined);
    morceaux.current = [];
    nouvel.ondataavailable = (evenement) => {
      if (evenement.data.size) morceaux.current.push(evenement.data);
    };
    nouvel.onstop = () => {
      const audio = morceaux.current.length ? new Blob(morceaux.current, { type: nouvel.mimeType || "audio/webm" }) : null;
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

  return { enregistre, duree, demarrer, arreter };
}
