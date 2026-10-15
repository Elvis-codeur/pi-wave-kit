# EN -> FR Reformed theology glossary (R.C. Sproul vocabulary)

Use the FR column unless the speaker's own argument needs another word (see Traps). Inside a verbatim Segond cue, Segond's
word always wins.

Source codes (all checked 2026-10-02):
- `LSG ref` = Segond 1910 text returned by `agentic_doc.translate.resolve_french_verse(book, chapter, verse)`.
- `C file k/n` = this repo's reviewed Sproul translations (`adf/video/*sproul*.fr.md`): of n English cues containing the
  term, k have the rendering in the same or a neighbouring French cue. `file` is a filename prefix with one example.
- `X id` = entry in `src/agentic_doc/data/fr_lexicon.yaml`. `R id` = wave-review edit (TranslatedChunkRevision id).
- `G` = `THEOLOGICAL_GLOSSARY` in `src/agentic_doc/terminology_audit.py`.
- `CHOICE` = corpus is split; the rendering given is a recommendation, not a verified fact.

## Traps (read first)
| EN | FR | Why / source |
|---|---|---|
| God-breathed, theopneustos | soufflé par Dieu | when contrasted with "inspired"; X godbreathed-inspire, R 1685, 1686. Segond 2 Tim 3:16 itself says "inspirée de Dieu" (LSG 2 Tim 3:16) |
| washing (of regeneration) | lavage | never "baptême" in his argument: X washing-bapteme, R 1571-1573. Segond Titus 3:5 reads "le baptême de la régénération" (LSG Titus 3:5): in a verbatim cue where he argues washing ≠ baptism, use "lavage" and note "deviates from Segond" |
| authoritative | qui fait autorité, faire autorité | never "autoritaire" (= domineering): X authoritative-autoritaire, R 1688, 1689 |
| ransomed | racheté, délivré par rançon | never "rançonné" (= extorted): X ransom-rancon, R 1574. The noun "ransom" = "rançon" (LSG Mark 10:45) |
| worship (God) | adorer, rendre un culte | never "vénérer": X worship-venerer, R 1607 |
| nurture | éducation | never "nourriture": X nurture-nourriture, R 1358 |
| the Word of God (Scripture) | la Parole de Dieu | not "le Verbe"; C a-basket-case 137/143 |
| the Word (Logos, John 1) | la Parole (Segond: "elle") | LSG John 1:1, 1:12. Outside the verse, Christ is "il/lui": R 1559, 1392. He says "Logos": keep Logos (C early-controversies 13/13) |
| holiness (Heb 12:14) | la sanctification | Segond's word in that verse (LSG Heb 12:14); elsewhere "sainteté" |
| propitiation (in a verse) | victime propitiatoire / victime expiatoire | LSG Rom 3:25 / 1 John 2:2, 4:10 |
| natural man (1 Cor 2:14) | l'homme animal (verse) / l'homme naturel (comment) | LSG 1 Cor 2:14; C effectual-calling 4/6 |
| unwilling | ne veulent pas | not "peu disposés": R 1569 |
| came from God (creation) | sortis des mains de Dieu | "sortis de Dieu" = emanation: R 1557 |
| right and wrong | le bien et le mal | X right-wrong-juste-faux |
| Boy, (interjection) | Eh bien, | never "Mon Dieu": X boy-mon-dieu, R 1560 |

## God
| EN | FR | Source |
|---|---|---|
| holiness | sainteté | C angels-and-demons 94/95 |
| Holy, holy, holy | Saint, saint, saint | LSG Isa 6:3; C angels-and-demons 23/23 |
| the Holy One (of Israel) | le Saint (d'Israël) | LSG Isa 1:4; R 1389 |
| the LORD (OT name) / the Lord | l'Éternel / le Seigneur | LSG Isa 6:3, Rom 5:1 |
| the Lord of hosts | l'Éternel des armées | LSG Isa 6:3; C r-c-sproul-holy-holy-holy 6/6 |
| I AM | Je suis celui qui suis | LSG Ex 3:14 |
| the Almighty | le Tout-Puissant | LSG Rev 4:8 |
| Woe is me! | Malheur à moi ! | LSG Isa 6:5; C ferguson-nichols 9/9 |
| unclean | impur | LSG Isa 6:5; C ferguson-nichols 20/22 |
| aseity | aséité | C r-c-sproul-before-the-beginning 1/1 |
| self-existent | auto-existant (also "qui existe par lui-même") | C r-c-sproul-before-the-beginning 11/30, r-c-sproul-defending-the-faith 2/30; CHOICE |
| sovereignty / sovereign | souveraineté / souverain | C a-simple-way-to-pray 85/85, 107/107; G |
| sovereignly | souverainement | C all-christians-believe 19/20 |
| providence | providence | C berkeley-and-empiricism 32/32; G |
| immutable | immuable | C a-simple-way-to-pray 13/13 |
| omniscient / omnipresent | omniscient / omniprésent | C a-simple-way-to-pray 21/21, 3/3 |
| transcendence | transcendance | C a-basket-case 40/40 |
| majesty / glory | majesté / gloire | C a-simple-way-to-pray 19/20; a-basket-case 193/203 |
| wrath | colère | LSG Rom 1:18; C adoption-union 73/74 |
| mercy | miséricorde | LSG Rom 9:15; C a-simple-way-to-pray 178/197 |
| Creator / creature | Créateur / créature | C adoption-union 37/37; a-basket-case 124/139 |
| foreknew | connus d'avance | LSG Rom 8:29; C effectual-calling 9/9 |
| foreknowledge | prescience | LSG Acts 2:23, 1 Pet 1:2. Corpus split: préconnaissance 19/27, prescience 9/27 (all-christians-believe); CHOICE |
| decree | décret | C all-christians-believe 39/60 |
| second causes / concurrence | causes secondes / concours | C god-s-sovereignty 3/3; free-will-and-divine-sovereignty 2/3 |
| mysterium tremendum, trisagion, coram Deo | keep as said | C the-meaning-of-holiness, r-c-sproul-a-holy-vision, pontius-pilate |

## Trinity and Christ
| EN | FR | Source |
|---|---|---|
| the Trinity | la Trinité | C catholic-evangelical-and-reformed 41/41 |
| Father, Son, Holy Spirit | le Père, le Fils, le Saint-Esprit | LSG Matt 28:19; C adoption-union 139/197 |
| Godhead | la Déité / la divinité | C covenant-what-is 5/9, general-revelation 4/9; CHOICE |
| person(s) / essence / substance | personne(s) / essence / substance | C covenant-what-is 11/11; a-basket-case 81/85, 36/38 |
| homoousios / homoiousios | keep Greek | C a-basket-case 10/10 |
| only begotten Son | Fils unique | LSG John 3:16; C a-basket-case 19/20 |
| begotten | engendré | C a-basket-case 17/32 |
| incarnation / virgin birth | incarnation / naissance virginale | C adoption-union 23/23; common-grace 15/15 |
| Son of Man | Fils de l'homme | LSG Mark 10:45; C a-basket-case 37/37 |
| Messiah | Messie | C a-basket-case 67/67 |
| the Lamb of God | l'Agneau de Dieu | LSG John 1:29 |
| mediator | médiateur | LSG 1 Tim 2:5; C anselm 30/30 |
| intercession | intercession | G; C healing-of-the-leper 6/8 |
| active obedience | obéissance active | C covenant-what-is 7/10 |

## Salvation
| EN | FR | Source |
|---|---|---|
| grace | grâce | LSG Eph 2:8; C a-simple-way-to-pray 517/525; G |
| grace alone / sola gratia | la grâce seule / sola gratia | C bondage-of-the-will 17/37, 27/37 |
| faith alone / sola fide | la foi seule / sola fide | C all-christians-believe 146/173; contrast LSG Jas 2:24 "par la foi seulement" |
| Scripture alone / sola Scriptura | l'Écriture seule / sola Scriptura | C lawson-macarthur 8/36, catholic-evangelical 31/36 |
| Christ alone / solus Christus | Christ seul / solus Christus | C faith-alone-part-1 33/34 |
| soli Deo gloria | à Dieu seul la gloire | C bondage-of-the-will 1/1 |
| justification / justified | justification / justifié | LSG Rom 4:25, Rom 5:1; C adoption-union 587/590; G |
| justifies the ungodly | justifie l'impie | LSG Rom 4:5 |
| just and the justifier | juste tout en justifiant | LSG Rom 3:26 |
| declared righteous / forensic | déclaré juste / forensique | C faith-alone-the-righteousness 8/8; faith-alone-part-1 14/14 |
| impute / imputation | imputer / imputation | LSG Rom 4:6; C contradiction-vs-mystery 73/74 |
| counted as righteousness | imputé à justice | LSG Rom 4:3, Gen 15:6 |
| imputed / infused righteousness | justice imputée / justice infusée | C good-bad-fruit 3/6; protestant-view-of-justification 3 |
| righteousness / righteous | justice / juste | LSG Rom 1:17, 3:10; C a-simple-way-to-pray 324/326, 163/164; G |
| ungodly / unrighteous | impie / injuste | LSG Rom 4:5; C anselm 9/14, ask-r-c-live 25/25 |
| atonement / the Day of Atonement | expiation / le jour des expiations | LSG Lev 16:30, Heb 2:17; C anselm 91/91, faith-alone-part-2 14/14; G |
| propitiation / expiation | propitiation / expiation | C r-c-sproul-christ-crucified 6/7, 6/6; G |
| mercy seat | propitiatoire | C ask-r-c-live 9/9 |
| limited atonement | expiation limitée | C irresistible-grace 9/11 |
| satisfaction / substitute | satisfaction / substitut | C anselm 49/53; abraham-and-isaac 36/37 |
| redemption / redeemed | rédemption / racheté | LSG Eph 1:7, 1 Pet 1:18; C abraham-and-isaac 72/72; G |
| remission of sins | rémission des péchés | LSG Eph 1:7 |
| reconciliation | réconciliation | LSG 2 Cor 5:19; G |
| forgiveness | pardon | LSG Heb 9:22; C all-christians-believe 36/36 |
| salvation / saving faith | salut / foi salvatrice | C a-basket-case 259/259; all-christians-believe 18/26 |
| regeneration / regenerate | régénération / régénéré | C all-christians-believe 49/50, 21/21; G |
| born again | né de nouveau / naître de nouveau | LSG John 3:3 |
| effectual calling | appel efficace | C effectual-calling 6/6 |
| inward / outward call | appel interne / appel externe | C effectual-calling 1/3, 1/1 |
| called (Rom 8:30) | appelés | LSG Rom 8:30 |
| quicken, make alive | vivifier (Segond: "rendus à la vie") | C all-christians-believe 20/27; LSG Eph 2:5 |
| monergism / synergism | monergisme / synergisme | C effectual-calling 6/6, 4/4 |
| ordo salutis | ordo salutis / ordre du salut | C paul-vs-james, effectual-calling |
| repentance | repentance | LSG 2 Cor 7:10; C angels-and-demons 52/56; G |
| sanctification | sanctification | LSG 1 Thess 4:3; C ask-r-c-live 63/63; G |
| adoption | adoption | LSG Rom 8:15; C adoption-union 19/19; G |
| glorification / glorified | glorification / glorifiés | LSG Rom 8:30; C effectual-calling 20/20 |
| perseverance of the saints | persévérance des saints | C perseverance-of-the-saints 8/8 |

## Sin and the will
| EN | FR | Source |
|---|---|---|
| the Fall / fallen | la chute / déchu | C all-christians-believe 55/57, a-simple-way-to-pray 111/130 |
| fallenness | déchéance | C all-christians-believe 15/19 |
| original sin | péché originel | LSG Ps 51:5 context; C bondage-of-the-will 58/58 |
| total depravity | dépravation totale | C how-does-truth-relate 25/25 |
| dead in trespasses and sins | morts par vos offenses et par vos péchés | LSG Eph 2:1 |
| spiritually dead | spirituellement mort | C all-christians-believe |
| the flesh | la chair | LSG Rom 8:7; C a-simple-way-to-pray 86/90 |
| iniquity / transgression | iniquité / transgression | LSG Ps 103:12, Isa 1:4; C bondage-of-the-will 24/25 |
| guilt / guilty | culpabilité / coupable | C angels-and-demons 76/81, 39/40 |
| free will | libre arbitre | C all-christians-believe 50/50 |
| bondage of the will | serf arbitre | C bondage-of-the-will 9/11 |
| moral / natural (in)ability | (in)capacité morale / capacité naturelle | C bondage-of-the-will 22/22; man-s-radical-fallenness 6/6 |
| image of God | image de Dieu | C ask-r-c-live 16/16 |
| Pelagian / semi-Pelagian | pélagien / semi-pélagien | C all-christians-believe 76/76, 47/47 |
| Arminian | arminien | C all-christians-believe 39/54 |

## Election and covenant
| EN | FR | Source |
|---|---|---|
| election / the elect | élection / les élus | LSG Rom 9:11, Eph 1:4; C all-christians-believe 101/101; G |
| predestination / predestined | prédestination / prédestinés | LSG Rom 8:29, Eph 1:5; C all-christians-believe 181/183; G |
| reprobation / double predestination | réprobation / double prédestination | C does-god-create-unbelief 2/2, 3/3 |
| unconditional election / irresistible grace | élection inconditionnelle / grâce irrésistible | C irresistible-grace 9/9, 9/9 |
| common grace | grâce commune | C ask-r-c-live 11/11 |
| covenant / new covenant | alliance / alliance nouvelle | LSG Jer 31:31; C abraham-and-isaac 135/143; G |
| covenant of works / of grace | alliance des œuvres / alliance de grâce | C covenant-what-is 16/16, 9/9 |

## Scripture and Church
| EN | FR | Source |
|---|---|---|
| Scripture / the Scriptures | l'Écriture / les Écritures | LSG 2 Tim 3:16, 1 Cor 15:3; C a-simple-way-to-pray 389/480 |
| infallible / inerrant | infaillible / inerrant | C all-christians-believe 59/59; contradiction-vs-mystery 41/42 |
| inspiration | inspiration | C a-simple-way-to-pray 29/29 |
| general / special revelation | révélation générale / spéciale | C general-revelation 23/23, 13/16 |
| natural theology | théologie naturelle | C general-revelation 11/11 |
| the Gospel | l'Évangile | LSG Rom 1:16; C a-basket-case 448/466 |
| the Law | la loi | C all-christians-believe 155/159 |
| the Reformation / Reformers / Reformed | la Réforme / les Réformateurs / réformé | C ask-r-c-live 89/106; 76/76; 149/153 |
| sacrament / baptism | sacrement / baptême | C ask-r-c-live 113/119; 93/93 |
| the Lord's Supper / the Lord's Prayer | la sainte Cène / le Notre Père | C discipleship 12/12; a-simple-way-to-pray 23/23 |
| creed (Apostles') | symbole (des apôtres) | C a-simple-way-to-pray 41/55 |
| penance / indulgence / purgatory | pénitence / indulgence / purgatoire | C ask-r-c-live 67/67; faith-alone-part-2 62/63, 40/40 |
| mortal sin / treasury of merit | péché mortel / trésor des mérites | C ask-r-c-live 73/73; faith-alone-the-righteousness 14/23 |
| Synod of Dort | synode de Dordrecht | R 1568 |
| high priest | souverain sacrificateur | LSG Heb 4:15; C a-basket-case 23/41 (grand prêtre 13); CHOICE |
| holy of holies | lieu très saint | LSG Heb 9:12; C holiness-and-justice 10/13 |
| fellowship / godliness | communion / piété | C adoption-union 24/27; blessings-curses 8/9 |
| worship (noun) | culte | C a-basket-case 137/199; LSG Rom 12:1 |
