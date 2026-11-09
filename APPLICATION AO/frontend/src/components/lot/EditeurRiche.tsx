import { Highlight } from "@tiptap/extension-highlight";
import { Table, TableCell, TableHeader, TableRow } from "@tiptap/extension-table";
import { TextAlign } from "@tiptap/extension-text-align";
import { TextStyleKit } from "@tiptap/extension-text-style";
import { EditorContent, useEditor, useEditorState, type Editor } from "@tiptap/react";
import { StarterKit } from "@tiptap/starter-kit";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Heading3,
  Heading4,
  Italic,
  List,
  ListOrdered,
  Redo2,
  Strikethrough,
  Table as IconeTableau,
  Underline,
  Undo2,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

/** Couleur de fond des cellules de tableau (« remplissage »), conservée dans le HTML. */
const attributFond = {
  backgroundColor: {
    default: null,
    parseHTML: (element: HTMLElement) => element.style.backgroundColor || null,
    renderHTML: (attributs: { backgroundColor?: string | null }) =>
      attributs.backgroundColor ? { style: `background-color: ${attributs.backgroundColor}` } : {},
  },
};
const CelluleColoree = TableCell.extend({
  addAttributes() {
    return { ...this.parent?.(), ...attributFond };
  },
});
const EnteteColore = TableHeader.extend({
  addAttributes() {
    return { ...this.parent?.(), ...attributFond };
  },
});

/**
 * Extensions créées une seule fois : si la liste changeait à chaque rendu, TipTap
 * réappliquerait ses options pendant la saisie (curseur déplacé, frappes perdues).
 */
const EXTENSIONS = [
  StarterKit.configure({ heading: { levels: [3, 4] }, link: false, code: false, codeBlock: false }),
  TextStyleKit,
  Highlight.configure({ multicolor: true }),
  TextAlign.configure({ types: ["heading", "paragraph"] }),
  Table.configure({ resizable: false }),
  TableRow,
  EnteteColore,
  CelluleColoree,
];

const POLICES = ["Arial", "Calibri", "Times New Roman"];
const TAILLES = ["8pt", "9pt", "10pt", "11pt", "12pt", "14pt", "16pt"];

export interface ChampInserable {
  cle: string;
  libelle: string;
}

interface Proprietes {
  valeur: string;
  surChangement: (html: string) => void;
  police: string;
  taille: number;
  libelle: string;
  /** Champs automatiques proposés à l'insertion (pièces administratives). */
  champs?: ChampInserable[];
}

export default function EditeurRiche({ valeur, surChangement, police, taille, libelle, champs }: Proprietes) {
  // Le contenu n'est lu qu'à la création : l'éditeur est ensuite la seule source de vérité
  // (le composant est recréé quand on change d'élément, grâce à sa clé).
  const [contenuInitial] = useState(valeur);
  const proprietes = useMemo(() => ({ attributes: { "aria-label": libelle, class: "editeur-contenu" } }), [libelle]);
  const editeur = useEditor({
    extensions: EXTENSIONS,
    content: contenuInitial,
    editorProps: proprietes,
    onUpdate: ({ editor }) => surChangement(editor.isEmpty ? "" : editor.getHTML()),
  });

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-bordure-forte">
      {editeur && <BarreOutils editeur={editeur} champs={champs} />}
      <div
        className="editeur-page max-h-[60vh] min-h-56 overflow-y-auto bg-white px-6 py-5 text-[#1a1a1a]"
        style={{ fontFamily: `"${police}", "Liberation Sans", Arial, sans-serif`, fontSize: `${taille}pt` }}
      >
        <EditorContent editor={editeur} />
      </div>
    </div>
  );
}

function BarreOutils({ editeur, champs }: { editeur: Editor; champs?: ChampInserable[] }) {
  const etat = useEditorState({
    editor: editeur,
    selector: ({ editor }) => ({
      gras: editor.isActive("bold"),
      italique: editor.isActive("italic"),
      souligne: editor.isActive("underline"),
      barre: editor.isActive("strike"),
      puces: editor.isActive("bulletList"),
      numeros: editor.isActive("orderedList"),
      titre3: editor.isActive("heading", { level: 3 }),
      titre4: editor.isActive("heading", { level: 4 }),
      gauche: editor.isActive({ textAlign: "left" }),
      centre: editor.isActive({ textAlign: "center" }),
      droite: editor.isActive({ textAlign: "right" }),
      justifie: editor.isActive({ textAlign: "justify" }),
      dansTableau: editor.isActive("table"),
      police: (editor.getAttributes("textStyle").fontFamily as string | undefined) ?? "",
      taille: (editor.getAttributes("textStyle").fontSize as string | undefined) ?? "",
      peutAnnuler: editor.can().undo(),
      peutRetablir: editor.can().redo(),
    }),
  });
  const chaine = () => editeur.chain().focus();

  return (
    <div className="flex flex-col gap-1 border-b border-bordure-forte bg-surface-2 p-1.5" role="toolbar" aria-label="Mise en forme du texte">
      <div className="flex flex-wrap items-center gap-1">
        <select
          aria-label="Police"
          value={etat.police}
          onChange={(e) => (e.target.value ? chaine().setFontFamily(e.target.value).run() : chaine().unsetFontFamily().run())}
          className="h-10 rounded-md border border-bordure-forte bg-fond px-2 text-xs text-texte"
        >
          <option value="">Police du document</option>
          {POLICES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select
          aria-label="Taille du texte"
          value={etat.taille}
          onChange={(e) => (e.target.value ? chaine().setFontSize(e.target.value).run() : chaine().unsetFontSize().run())}
          className="h-10 rounded-md border border-bordure-forte bg-fond px-2 text-xs text-texte"
        >
          <option value="">Taille</option>
          {TAILLES.map((t) => (
            <option key={t} value={t}>
              {t.replace("pt", " pt")}
            </option>
          ))}
        </select>
        <Separateur />
        <Bouton libelle="Gras" actif={etat.gras} surClic={() => chaine().toggleBold().run()}><Bold className="size-4" /></Bouton>
        <Bouton libelle="Italique" actif={etat.italique} surClic={() => chaine().toggleItalic().run()}><Italic className="size-4" /></Bouton>
        <Bouton libelle="Souligné" actif={etat.souligne} surClic={() => chaine().toggleUnderline().run()}><Underline className="size-4" /></Bouton>
        <Bouton libelle="Barré" actif={etat.barre} surClic={() => chaine().toggleStrike().run()}><Strikethrough className="size-4" /></Bouton>
        <Couleur libelle="Couleur du texte" valeurInitiale="#c00000" surChoix={(c) => chaine().setColor(c).run()} surEffacer={() => chaine().unsetColor().run()} lettre="A" />
        <Couleur libelle="Surlignage" valeurInitiale="#fff59d" surChoix={(c) => chaine().setHighlight({ color: c }).run()} surEffacer={() => chaine().unsetHighlight().run()} lettre="S" />
        <Separateur />
        <Bouton libelle="Titre" actif={etat.titre3} surClic={() => chaine().toggleHeading({ level: 3 }).run()}><Heading3 className="size-4" /></Bouton>
        <Bouton libelle="Sous-titre" actif={etat.titre4} surClic={() => chaine().toggleHeading({ level: 4 }).run()}><Heading4 className="size-4" /></Bouton>
        <Bouton libelle="Liste à puces" actif={etat.puces} surClic={() => chaine().toggleBulletList().run()}><List className="size-4" /></Bouton>
        <Bouton libelle="Liste numérotée" actif={etat.numeros} surClic={() => chaine().toggleOrderedList().run()}><ListOrdered className="size-4" /></Bouton>
        <Separateur />
        <Bouton libelle="Aligner à gauche" actif={etat.gauche} surClic={() => chaine().setTextAlign("left").run()}><AlignLeft className="size-4" /></Bouton>
        <Bouton libelle="Centrer" actif={etat.centre} surClic={() => chaine().setTextAlign("center").run()}><AlignCenter className="size-4" /></Bouton>
        <Bouton libelle="Aligner à droite" actif={etat.droite} surClic={() => chaine().setTextAlign("right").run()}><AlignRight className="size-4" /></Bouton>
        <Bouton libelle="Justifier" actif={etat.justifie} surClic={() => chaine().setTextAlign("justify").run()}><AlignJustify className="size-4" /></Bouton>
        <Separateur />
        <Bouton libelle="Insérer un tableau" actif={false} surClic={() => chaine().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}>
          <IconeTableau className="size-4" />
        </Bouton>
        {champs && champs.length > 0 && (
          <select
            aria-label="Insérer un champ automatique"
            value=""
            onChange={(e) => {
              if (e.target.value) chaine().insertContent(`{{${e.target.value}}}`).run();
            }}
            className="h-10 max-w-48 rounded-md border border-accent/50 bg-fond px-2 text-xs text-accent"
          >
            <option value="">Insérer un champ…</option>
            {champs.map((c) => (
              <option key={c.cle} value={c.cle}>
                {c.libelle}
              </option>
            ))}
          </select>
        )}
        <Bouton libelle="Annuler" actif={false} desactive={!etat.peutAnnuler} surClic={() => chaine().undo().run()}><Undo2 className="size-4" /></Bouton>
        <Bouton libelle="Rétablir" actif={false} desactive={!etat.peutRetablir} surClic={() => chaine().redo().run()}><Redo2 className="size-4" /></Bouton>
      </div>
      {etat.dansTableau && (
        <div className="flex flex-wrap items-center gap-1 border-t border-bordure pt-1" aria-label="Tableau">
          <span className="px-1.5 text-xs text-attenue">Tableau :</span>
          <BoutonTexte surClic={() => chaine().addRowAfter().run()}>+ ligne</BoutonTexte>
          <BoutonTexte surClic={() => chaine().addColumnAfter().run()}>+ colonne</BoutonTexte>
          <BoutonTexte surClic={() => chaine().deleteRow().run()}>− ligne</BoutonTexte>
          <BoutonTexte surClic={() => chaine().deleteColumn().run()}>− colonne</BoutonTexte>
          <BoutonTexte surClic={() => chaine().mergeOrSplit().run()}>Fusionner / scinder</BoutonTexte>
          <BoutonTexte surClic={() => chaine().toggleHeaderRow().run()}>Ligne d'en-tête</BoutonTexte>
          <Couleur
            libelle="Couleur de fond des cellules"
            valeurInitiale="#fff2cc"
            surChoix={(c) => chaine().setCellAttribute("backgroundColor", c).run()}
            surEffacer={() => chaine().setCellAttribute("backgroundColor", null).run()}
            lettre="▦"
          />
          <BoutonTexte surClic={() => chaine().deleteTable().run()} danger>
            Supprimer le tableau
          </BoutonTexte>
        </div>
      )}
    </div>
  );
}

function Bouton({ libelle, actif, surClic, desactive = false, children }: { libelle: string; actif: boolean; surClic: () => void; desactive?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={libelle}
      title={libelle}
      aria-pressed={actif}
      disabled={desactive}
      onMouseDown={garderLeFocus}
      onClick={surClic}
      className={`grid size-10 place-items-center rounded-md transition-colors disabled:opacity-35 ${
        actif ? "bg-accent text-sur-accent" : "text-texte hover:bg-bordure-forte"
      }`}
    >
      {children}
    </button>
  );
}

function BoutonTexte({ surClic, children, danger = false }: { surClic: () => void; children: ReactNode; danger?: boolean }) {
  return (
    <button
      type="button"
      onMouseDown={garderLeFocus}
      onClick={surClic}
      className={`h-9 rounded-md px-2.5 text-xs font-medium ${danger ? "text-danger hover:bg-danger/10" : "text-texte hover:bg-bordure-forte"}`}
    >
      {children}
    </button>
  );
}

function Couleur({
  libelle,
  valeurInitiale,
  surChoix,
  surEffacer,
  lettre,
}: {
  libelle: string;
  valeurInitiale: string;
  surChoix: (couleur: string) => void;
  surEffacer: () => void;
  lettre: string;
}) {
  return (
    <span className="flex items-center rounded-md border border-bordure-forte">
      <label className="relative grid size-10 cursor-pointer place-items-center" title={libelle}>
        <span aria-hidden="true" className="text-sm font-bold text-texte">
          {lettre}
        </span>
        <input
          type="color"
          aria-label={libelle}
          defaultValue={valeurInitiale}
          onChange={(e) => surChoix(e.target.value)}
          className="absolute inset-x-1.5 bottom-1 h-1.5 w-7 cursor-pointer appearance-none border-0 bg-transparent p-0"
        />
      </label>
      <button
        type="button"
        onMouseDown={garderLeFocus}
        onClick={surEffacer}
        aria-label={`Retirer : ${libelle.toLowerCase()}`}
        title="Retirer"
        className="grid h-10 w-6 place-items-center text-xs text-attenue hover:text-texte"
      >
        ×
      </button>
    </span>
  );
}

/** Les boutons de la barre d'outils ne prennent pas le focus : le curseur reste dans le texte. */
function garderLeFocus(evenement: React.MouseEvent) {
  evenement.preventDefault();
}

function Separateur() {
  return <span aria-hidden="true" className="mx-0.5 h-6 w-px bg-bordure-forte" />;
}
