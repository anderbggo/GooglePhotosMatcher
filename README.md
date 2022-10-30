# Google Photos Matcher (v 1.2)

Simple executable to match metadata from JSONs to original images/videos.

Same work than [MetadataFixer](https://metadatafixer.com/pricing) but its free!

## Wiki 📖

When you download the images from google photos, they lose some metadata such as the date and the coordinates in which they were taken.

This algorithm is able to match this information in the image/video from the downloaded JSONs

## Usage

1. Download your _Google Photos_ media from [Takeout](https://takeout.google.com/)

2. Download and execute GPMatcher.exe

3. [Optional] Type custom suffix used for edited photos (explained in the program)

4. Select the folder in which images/videos along with its JSONs were downloaded ('Photos from 2022' for example)

5. Click on _Match_ button

6. Matched images/videos will be on directory _Matched_ inside the same path

## FAQs

### Why is there another folder called _EditedRaw_?

Images and videos edited from _Google Photos's_ editor will have 2 different versions: 

  1. Edited version
  2. Original version
  
Edited version will be stored in _Matched_ while original in _EditedRaw_

### Why some images/videos stay unmatched?

Sometimes, the algorithm does not recognize the names of the images due to the presence of some special characters. These files will remain in the same folder. To fix it, rename both the JSON and the original file.

#### For example: 

  - Algorithm fails with image _%E&xample.jpg_


#### Solution

1. Rename _%E&xample.jpg_ to _Example.jpg_ and _%E&xample.json_ to _Example.json_ 

2. Open JSON and change title attribute to _Example.jpg_

3. Run again

## Contributors ✒️

* **anderbggo** - Author
* **Freepik** - Icon creator

## Donations💰

* BTC -> 14BJjSVqUcLKFkPHBHwNenm2j5qWcwqUyb
* ETH -> 0x910c055988973b03b9c517bab62198e9ee550f65
* USDT (TRC20) -> TRAp5UiRoEMvQVzd7d6wDHZg2Uwu6eVvaX
* USDT (BEP20) -> 0x910c055988973b03b9c517bab62198e9ee550f65
* LTC -> LcF2dm2gRqHMHLP4snQFb1zyaUwDfLb443
