# Ambulances : carte, ETA et GPS réel

Bouton gauche **Ambulances** : carte Leaflet + OpenStreetMap centrée sur la clinique (coordonnées **fictives** à Tunis),
position des ambulances en temps réel, itinéraire, heure d'arrivée estimée (ETA) recalculée chaque seconde.

## Déroulé
1. **Fiche d'intervention** : patient (déjà connu ou nouveau), motif, type d'urgence (traumatologie, cardiologie, AVC,
   détresse respiratoire, obstétrique, infection, autre), gravité (P1 à P3), constantes transmises par l'équipe.
2. **Départ** : une chambre adaptée est **réservée automatiquement** parmi les chambres libres (ordre de préférence par
   type d'urgence), affichée « Réservée — arrivée dans X min » dans la plateforme et au-dessus du lit dans la 3D ;
   infirmiers et médecin de garde reçoivent la préparation (matériel, équipe, examens), précisée par le workflow n8n
   `ambulance-dispatch`. S'il n'y a aucune chambre libre, le départ est refusé : faire d'abord la sortie d'un patient.
3. **Trajet** : position et ETA mises à jour en continu (WebSocket).
4. **Arrivée** (ETA à zéro) : dans la 3D, l'ambulance du parking fait son entrée (gyrophare), un brancard va de l'entrée à
   la chambre réservée ; après `AMBULANCE_INSTALL_S` secondes, le patient est installé au lit et **l'admission est créée**.

## GPS simulé (par défaut)
L'ambulance suit une polyligne embarquée (4 trajets autour de Tunis : La Marsa, centre, Ariana, trajet court) à vitesse
variable (départ, portion rapide, ralentissements). Aucun service de routage externe n'est nécessaire.

| Variable | Défaut | Rôle |
|---|---|---|
| `AMBULANCE_TIME_SCALE` | `1` | accélère le trajet simulé (ex. `8` : 9 km en ~1 min 30) |
| `AMBULANCE_ARRIVAL_M` | `60` | distance à la clinique en dessous de laquelle l'ambulance est « arrivée » |
| `AMBULANCE_INSTALL_S` | `20` | durée du transfert de l'entrée à la chambre avant la création de l'admission |

## GPS réel (téléphone d'un coéquipier)
Chaque mission a un lien **« 📱 Suivi GPS réel »** : `/ambulance/track/<jeton>`. Ouvert sur un téléphone, il demande
l'autorisation de géolocalisation puis envoie la position au serveur **toutes les 2 secondes** (API Geolocation du
navigateur). Dès la première position reçue, le téléphone remplace le trajet simulé : la personne qui marche avec son
téléphone déplace l'ambulance sur la carte. Le bouton « Arrivé à la clinique » déclenche l'arrivée ; elle se déclenche
aussi seule à moins de 60 m des coordonnées de la clinique.

Pour une démonstration en intérieur, les coordonnées de la clinique étant fictives, utiliser le bouton « Arrivé ».

### HTTPS obligatoire
Un navigateur ne donne la position que sur une page **HTTPS** (ou `localhost`). Le téléphone n'étant pas `localhost`,
deux solutions :

**A. Tunnel HTTPS (le plus simple)** — une URL publique chiffrée qui redirige vers le PC :
```powershell
# Cloudflare (sans compte) :
cloudflared tunnel --url http://localhost:8000
# ou ngrok (compte gratuit) :
ngrok http 8000
```
Ouvrir sur le téléphone `https://<adresse-du-tunnel>/ambulance/track/<jeton>` (le jeton est celui du lien affiché dans la
vue Ambulances). Le lien de suivi est protégé par ce jeton aléatoire, propre à la mission ; il ne donne accès à rien d'autre.

**B. Réseau local avec certificat auto-signé** — PC et téléphone sur le même Wi-Fi :
```powershell
# 1. certificat pour l'adresse IP du PC (ex. 192.168.1.20)
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -keyout key.pem -out cert.pem -subj "/CN=192.168.1.20" -addext "subjectAltName=IP:192.168.1.20"
# 2. lancer la plateforme en HTTPS
cd dashboard
..\.venv\Scripts\python -m uvicorn server:app --host 0.0.0.0 --port 8443 --ssl-keyfile ..\key.pem --ssl-certfile ..\cert.pem
```
Sur le téléphone : `https://192.168.1.20:8443/ambulance/track/<jeton>`, accepter l'avertissement du certificat, puis
autoriser la localisation. Penser à autoriser le port dans le pare-feu Windows. `key.pem` et `cert.pem` ne se commitent pas.

## API
| Méthode | Chemin | Rôle |
|---|---|---|
| `GET` | `/api/ambulances` | clinique, types, trajets, chambres libres, missions (position, ETA, itinéraire) |
| `POST` | `/api/ambulances/missions` | départ : crée la mission, réserve la chambre, prévient l'équipe |
| `POST` | `/api/ambulances/missions/{id}/cancel` | annule la mission et libère la réservation |
| `GET` / `POST` | `/api/ambulances/track/{jeton}` | page téléphone : état de la mission / envoi d'une position |

Messages WebSocket `ambulance` : `dispatched`, `position` (chaque seconde), `briefing`, `arrived`, `admitted`, `cancelled`.
