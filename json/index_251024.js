"use strict";

var l2dviewer;
var l2dmaster;
let mocname;
let currentAudioPlayer = null;

class l2dViewer{

    copyright = true
    _containers = new Map()
    _l2dModels = new Map()

    constructor(element){
        
        if (document.getElementById("viewer")) {
            document.getElementById("viewer").remove();
        }

        this._element = element
        this._app = new PIXI.Application({
            autoDensity: true,
            resolution: window.devicePixelRatio || 1,
            backgroundColor: 0x494A5A
        });

        globalThis.__PIXI_APP__ = this._app;
        this._app.view.setAttribute("id", "viewer");
        element.appendChild(this._app.view);

        this._resizeViwer();
        window.addEventListener('resize', this._resizeViwer.bind(this));

        let modelcontainer = new PIXI.Container();
        this._app.stage.addChild(modelcontainer);


        this._containers.set('Models', modelcontainer);

    }

    _resizeViwer() {
        let eleWidth = this._element.offsetWidth;
        let eleHeight = this._element.offsetHeight;
        this._app.renderer.resize(eleWidth, eleHeight);
    }


    addModel(model){
        if(this._l2dModels.has(model.getIndexName())){
            return;
        }

        this._l2dModels.set(model.getIndexName(), model);
        this._containers.get('Models').addChild(model._Model);


        model.setAnchor(0.5);
        model.setScale(0.15);
        model._Model.position.set(this._app.screen.width/2.5, this._app.screen.height/2);
        model.pointerEventBind();

        let foreground = PIXI.Sprite.from(PIXI.Texture.WHITE);
        foreground.width = model._Model.internalModel.width;
        foreground.height = model._Model.internalModel.height;
        foreground.alpha = 0.17;
        foreground.visible = false
        model.setForeground(foreground)

        console.log('model loaded')
    }

    removeModel(name) {
        let model = this._l2dModels.get(name);
        if (!model) {
            return;
        }
    
        // STOP AUDIO
        if (currentAudioPlayer) {
            currentAudioPlayer.pause();
            currentAudioPlayer.currentTime = 0;
            currentAudioPlayer = null;
        }
    
        // CLEAR TEXT
        let textContainer = document.getElementById('text-container');
        if (textContainer) {
            textContainer.style.opacity = 0;
        }
    
        // REMOVE Model
        this._containers.get('Models').removeChild(model._Model);
        model._Model.destroy();
        this._l2dModels.delete(name);
    
        console.log('model removed');
    }

    isModelInList(name){
        return this._l2dModels.has(name);
    }

    findModel(name){
        return this._l2dModels.get(name);
    }

}

PIXI.live2d.CubismConfig.setOpacityFromMotion = true

class HeroModel{

    _container = new PIXI.Container()

    async create(src){
        let settingsJSON = await fetch(src).then(res => res.json());
        settingsJSON.url = src;

        this._modelsetting = new PIXI.live2d.Cubism4ModelSettings(settingsJSON);
        this._Model = await PIXI.live2d.Live2DModel.from(settingsJSON);

        this._ParametersValues = {};

        this._ParametersValues.breath = [...this._Model.internalModel.breath._breathParameters] //Clone
        // this._Model.breathing = false
        // this._Model.internalModel.breath._breathParameters = [] //不搖頭

        this._ParametersValues.eyeBlink = [...this._Model.internalModel.eyeBlink._parameterIds] //Clone
        // this._Model.eyeBlinking = false
        // this._Model.internalModel.eyeBlink._parameterIds = [] //不眨眼

        this._ParametersValues.parameter = [] //Clone All Parameters Values
        this.getCoreModel()._parameterIds.map((p, index) => {
            let parameter = {}
            parameter.parameterIds = p
            parameter.max = this.getCoreModel()._parameterMaximumValues[index]
            parameter.min = this.getCoreModel()._parameterMinimumValues[index]
            parameter.defaultValue = this.getCoreModel()._parameterValues[index]

            this._ParametersValues.parameter.push(parameter)
        })

        this._ParametersValues.PartOpacity = [] //Clone All Part Opacity
        this.getCoreModel()._partIds.map((p, index) => {
            let part = {}
            part.partId = p
            part.defaultValue = this.getCoreModel().getPartOpacityById(p)

            this._ParametersValues.PartOpacity.push(part)
        })
    }

    pointerEventBind() {

        this._Model.autoInteract = false;
        this._Model.interactive = true;
        this._Model.focusing = false;
        this._Model.breathing = true;
        this._Model.eyeBlinking = true;

        this._Model.buttonMode = true;

        this._Model.on("pointerdown", (e) => {
            this._Model.dragging = true;
            this._Model._pointerX = e.data.global.x - this._Model.x;
            this._Model._pointerY = e.data.global.y - this._Model.y;
        });

        this._Model.on("pointermove", (e) => {
            if (this._Model.dragging) {
                this._Model.position.x = e.data.global.x - this._Model._pointerX;
                this._Model.position.y = e.data.global.y - this._Model._pointerY;
            }
        });

        this._Model.on("pointerupoutside", () => (this._Model.dragging = false));
        this._Model.on("pointerup", () => (this._Model.dragging = false));

        let viewer = document.getElementById('viewer');
        viewer.addEventListener('pointerdown', (e) => {
            if(this._Model.focusing)
                this._Model.focus(e.clientX, e.clientY)
        });
    }

    setName(char, cost){
        this._ModelName = char;
        this._costume = cost;
    }

    setAnchor(x, y){
        if(!y) y = x
        this._Model.anchor.set(x, y);
    }

    setScale(val){
        this._Model.scale.set(val)
    }

    setAlpha(val){
        this._Model.aplha = val
    }

    setAngle(val){
        this._Model.angle = val
    }

    setForeground(Sprite){
        this._Model.addChild(Sprite)
    }

    setForegroundVisible(bool){
        this._Model.children[0].visible = bool
    }

    setInteractive(bool){
        this._Model.interactive = bool
    }

    setLookatMouse(bool){
        this._Model.focusing = bool
        if(!bool){
            this._Model.focus(this._Model.x, this._Model.y)
        }
    }


    setParameters(id, value){
        this.getCoreModel().setParameterValueById(id, value)
    }

    setPartOpacity(id, value){
        this.getCoreModel().setPartOpacityById(id, value)
    }

    setBreathing(bool){
        this._Model.breathing = bool
        if(!this._Model.breathing){
            this._Model.internalModel.breath._breathParameters = []
            return
        }

        this._Model.internalModel.breath._breathParameters = [...this._ParametersValues.breath]
    }

    setEyeBlinking(bool){
        this._Model.eyeBlinking = bool
        if(!this._Model.eyeBlinking){
            this._Model.internalModel.eyeBlink._parameterIds = []
            return
        }

        this._Model.internalModel.eyeBlink._parameterIds = [...this._ParametersValues.eyeBlink]
    }

    loadExpression(index){
        this.getExpressionManager().setExpression(index)
    }

    executeMotionByName = (name, type = '') => {
        let index = this._getMotionByName(type, name)
        this.loadMotion(type, index, 'FORCE')
    }

    _getMotionByName = (type, name) => {
        let motions = this._modelsetting?.motions
        return motions[type].findIndex(motion => motion.Name == name)
    }

    loadMotion = (group, index, priority) => {
        this._Model.motion(group, index, priority)
    }


    getAnchor(){
        return this._Model.anchor
    }

    getScale(){
        return this._Model.scale
    }

    getAlpha(){
        return this.aplha
    }

    getAngle(){
        return this._Model.angle
    }

    getIndexName(){
        return `${this._ModelName}_${this._costume}`
    }

    getSetting(){
        return this._modelsetting
    }

    getUrl(){
        return this._modelsetting?.url
    }

    getGroups(){
        return this._modelsetting?.groups
    }

    getExpressions(){
        return this._modelsetting?.expressions
    }

    getMotions(){
        return this._modelsetting?.motions
    }

    getParamById(id){
        return this._ParametersValues.parameter.find(x => x.parameterIds == id)
    }

    getAllParameters(){
        return this._ParametersValues.parameter
    }

    getPartOpacityById(id){
        return this._ParametersValues.PartOpacity.find(x => x.partId == id)
    }

    getAllPartOpacity(){
        return this._ParametersValues.PartOpacity
    }

    getCoreModel(){
        return this._Model.internalModel.coreModel
    }

    getMotionManager(){
        return this._Model?.internalModel.motionManager
    }

    getFocusController(){
        return this._Model?.internalModel.focusController
    }

    getExpressionManager(){
        return this._Model?.internalModel.motionManager.expressionManager
    }

}

// SET UP GAME SELECT
const setupGameSelect = (data) => {
    let gameSelect = document.getElementById('gameSelect');
    let inner = `<option value="">选择游戏</option>`;
    
    data.Master.forEach(game => {
        inner += `<option value="${game.gameId}">${game.gameName}</option>`;
    });

    gameSelect.innerHTML = inner;

    gameSelect.onchange = (e) => {
        if (e.target.value === '') {
            document.getElementById('characterSelect').innerHTML = '<option value="">选择角色</option>';
            document.getElementById('costumeSelect').innerHTML = '<option value="">选择服装</option>';
            return;
        }

        let gameId = e.target.value;
        let gameData = data.Master.find(game => game.gameId == gameId);
        setupCharacterSelect(gameData);
    };
};

// SET UP CHAR SELECT
const setupCharacterSelect = (gameData) => {
    let select = document.getElementById('characterSelect');
    let inner = `<option value="">选择角色</option>`;

    gameData.character.forEach(character => {
        inner += `<option value="${character.charId}">${character.charName}</option>`;
    });

    select.innerHTML = inner;

    select.onchange = (e) => {
        if (e.target.value === '') {
            document.getElementById('costumeSelect').innerHTML = '<option value="">选择服装</option>';
            return;
        }

        let charId = e.target.value;
        let charData = gameData.character.find(char => char.charId == charId);
        setupCostumeSelect(charData);
    };
};

// SET UP COSTUME SELECT
const setupCostumeSelect = (character) => {
    let select = document.getElementById('costumeSelect');
    let inner = ``;

    character.live2d.forEach(costume => {
        inner += `<option value="${costume.costumeId}">${costume.costumeName}</option>`;
    });

    select.innerHTML = inner;
};

const toggleTabContainer = (tabid) => {
    let tabcons = document.getElementsByClassName('tab-content')
    Array.from(tabcons).forEach(element => {
        element.classList.remove('shown');
    })

    let tabbtns = document.getElementsByClassName('tab-btn')
    Array.from(tabbtns).forEach(element => {
        element.classList.remove('btn-selecting');
    })

    let ele = document.getElementById(tabid)
    ele?.classList.add('shown')

    let elebtn = document.getElementById(`${tabid}btn`)
    elebtn?.classList.add('btn-selecting')
}

const setupModelSetting = (M) => {
    let info_ModelName = document.getElementById('info-ModelName')
    let info_CostumeName = document.getElementById('info-CostumeName')

    info_ModelName.innerHTML = M._ModelName
    info_CostumeName.innerHTML = M._costume

    let backBtn = document.getElementById('back-btn')
    backBtn.onclick = () => {
        toggleTabContainer('Models')
    }

    Array.from(document.getElementsByClassName('collapsible')).forEach(x => {
        x.classList.remove('active')
        let content = x.nextElementSibling;
        content.style.display = "none";
    })


    //SET UP SCALE PARAMETER
    let scale_Range = document.getElementById('scaleRange')
    let scale_Num = document.getElementById('scaleNum')
    scale_Range.value = M.getScale().x
    scale_Num.value = scale_Range.value
    scale_Range.oninput = function(e) {
        scale_Num.value = this.value
        M.setScale(this.value)
    }
    scale_Num.oninput = function(e){
        if(this.value == ""){
            this.value = scale_Range.value
            return
        }

        if(parseInt(this.value) < parseInt(this.min)){
            this.value = this.min;
        }
        if(parseInt(this.value) > parseInt(this.max)){
            this.value = this.max;
        }
        scale_Range.value = this.value
        M.setScale(this.value)
    }

    //SET UP ANGLE PARAMETER
    let angle_Range = document.getElementById('angleRange')
    let angle_Num = document.getElementById('angleNum')
    angle_Range.value = M.getAngle()
    angle_Num.value = angle_Range.value
    angle_Range.oninput = function(e){
        angle_Num.value = this.value
        M.setAngle(this.value)
    }
    angle_Num.oninput = function(e){
        if(this.value == ""){
            this.value = angle_Range.value
            return
        }

        if(parseInt(this.value) < parseInt(this.min)){
            this.value = this.min;
        }
        if(parseInt(this.value) > parseInt(this.max)){
            this.value = this.max;
        }
        angle_Range.value = this.value
        M.setAngle(this.value)
    }



    //SET UP INTERACTIVE
    let focusingCheckbox = document.getElementById('FocusingCheckbox')
    focusingCheckbox.checked = M._Model.focusing
    focusingCheckbox.onchange = function(e){
        M.setLookatMouse(this.checked);
    }

    // SET UP BREATH
    let breathingCheckbox = document.getElementById('breathingCheckbox')
    breathingCheckbox.checked = M._Model.breathing
    breathingCheckbox.onchange = function(e){
        M.setBreathing(this.checked);
    }

    //SET UP EYEBLINKING
    let eyeBlinkingCheckbox = document.getElementById('eyeBlinkingCheckbox')
    eyeBlinkingCheckbox.checked = M._Model.eyeBlinking
    eyeBlinkingCheckbox.onchange = function(e){
        M.setEyeBlinking(this.checked);
    }

    // SET UP FOREGROUND
    let foregroundCheckbox = document.getElementById('foregroundCheckbox')
    foregroundCheckbox.checked = M._Model.children[0].visible
    foregroundCheckbox.onchange = function(e){
        M.setForegroundVisible(this.checked);
    }

    //Drag
    let dragCheckbox = document.getElementById('dragCheckbox')
    dragCheckbox.checked = M._Model.interactive
    dragCheckbox.onchange = function(e){
        M.setInteractive(this.checked)
    }


    //SET UP EXPRESSTIONS LIST
    let expressionslist = document.getElementById('expressions-list')
    let expressions = M.getExpressions()
    expressionslist.innerHTML = ''
    Array.from(expressions).forEach((exp, index)=>{
        let expbtn = document.createElement("button");
        let expbtnname = exp['Name']
        expbtn.innerHTML = expbtnname.replace(".exp3.json","")
        expbtn.addEventListener('click', ()=>{
            M.loadExpression(index)
        })

        expressionslist.append(expbtn)
    })

    //SET UP MOTIONS LIST
    let textCheckbox = document.getElementById('textCheckbox');
    let audioCheckbox = document.getElementById('audioCheckbox');
    let textContainer = document.getElementById('text-container');

    textCheckbox.addEventListener('change', () => {
        if (textCheckbox.checked) {
            textContainer.style.opacity = 1;
        } else {
            textContainer.style.opacity = 0;
        }
    });

    

    function motionButtonClickHandler(key, index, audioFileName, textContent) {
        return new Promise((resolve) => {
            // 如果有先前的音频正在播放，停止它
            if (currentAudioPlayer) {
                currentAudioPlayer.pause();
                currentAudioPlayer.currentTime = 0;
                currentAudioPlayer = null;  // 重置当前音频对象
            }

            textContainer.style.opacity = 0;

            // 如果有关联的音频文件名、复选框勾选状态以及文本框勾选状态，则创建新的音频对象并播放
            if (audioFileName && audioCheckbox.checked) {
                let audioFilePath = audioFileName;
                let audioPlayer = new Audio(audioFilePath);

                audioPlayer.onended = () => {
                    textContainer.style.opacity = 0; // 设置透明度为0，开始淡出
                    resolve();
                };

                audioPlayer.onplay = () => {
                    if (textContent && textCheckbox.checked) {
                        textContainer.innerHTML = textContent;
                        textContainer.style.opacity = 1;
                    }
                };
                audioPlayer.play();
                currentAudioPlayer = audioPlayer;
            } else {

                if (textContent && textCheckbox.checked) {
                    textContainer.innerHTML = textContent;
                    textContainer.style.opacity = 1;
                }
                resolve();
            }
        });
    }
    let motionslist = document.getElementById('motion-list')
    let motions = M.getMotions()
    motionslist.innerHTML = ''

    for (const key in motions) {
        Array.from(motions[key]).forEach((m, index) => {
            if (m['File'].includes('loop')) {
                return
            }

            let motionbtn = document.createElement("button");
            motionbtn.innerHTML = m['File'].replace("motions/", "").replace(".motion3.json", "")

            motionbtn.addEventListener("click", async () => {
                // 获取音频文件名和文本内容
                let audioFileName = m['Audio'] || null
                let textContent = m['Text'] || ''

                // 立即调用点击按钮的回调函数，不等待 Promise 解析
                motionButtonClickHandler(key, index, audioFileName, textContent)

                // 加载动作
                M.loadMotion(key, index, 'FORCE')
            })

            motionslist.append(motionbtn)
        });
    }

    //SET UP MODEL PARAMETER LIST
    let parameterslist = document.getElementById('parameters-list')
    let parameter = M.getAllParameters()
    parameterslist.innerHTML = ''

    parameter.map((param) => {
        let p_div = document.createElement("div");
        p_div.className = 'rangeOption'
        p_div.innerHTML += `<p>${param.parameterIds}</p>`

        let range = document.createElement("input");
        range.type = 'range'
        range.className = 'input-range'
        range.setAttribute('step', 0.01)
        range.setAttribute('min', param.min)
        range.setAttribute('max', param.max)
        range.value = param.defaultValue
        p_div.append(range)

        let text = document.createElement("input");
        text.type = 'number'
        text.setAttribute('step', 0.01)
        text.setAttribute('min', param.min)
        text.setAttribute('max', param.max)
        text.value = param.defaultValue
        p_div.append(text)

        range.addEventListener('input', function(e){
            text.value = this.value
            M.setParameters(param.parameterIds, this.value)
        })

        text.addEventListener('input', function(e){
            if(this.value == ""){
                this.value = range.value
                return
            }

            if(parseInt(this.value) < parseInt(this.min)){
                this.value = this.min;
            }
            if(parseInt(this.value) > parseInt(this.max)){
                this.value = this.max;
            }
            range.value = this.value
            M.setParameters(param.parameterIds, this.value)
        })

        parameterslist.append(p_div)
    })

    //SET UP MODEL PartOpacity LIST
    let partOpacityList = document.getElementById('partOpacity-list')
    let partOpacity = M.getAllPartOpacity()
    partOpacityList.innerHTML = ''

    partOpacity.map((param) => {
        let p_div = document.createElement("div");
        p_div.className = 'rangeOption'
        p_div.innerHTML += `<p>${param.partId}</p>`

        let range = document.createElement("input");
        range.type = 'range'
        range.className = 'input-range'
        range.setAttribute('step', 0.1)
        range.setAttribute('min', 0)
        range.setAttribute('max', 1)
        range.value = param.defaultValue
        p_div.append(range)

        let text = document.createElement("input");
        text.type = 'number'
        text.setAttribute('step', 0.1)
        text.setAttribute('min', 0)
        text.setAttribute('max', 1)
        text.value = param.defaultValue
        p_div.append(text)

        range.addEventListener('input', function(e){
            text.value = this.value
            M.setPartOpacity(param.partId, this.value)
        })

        text.addEventListener('input', function(e){
            if(this.value == ""){
                this.value = range.value
                return
            }

            if(parseInt(this.value) < parseInt(this.min)){
                this.value = this.min;
            }
            if(parseInt(this.value) > parseInt(this.max)){
                this.value = this.max;
            }
            range.value = this.value
            M.setPartOpacity(param.partId, this.value)
        })

        partOpacityList.append(p_div)
    })

}

$(document).ready(async () => {
    let l2dmaster
    await fetch('./json/live2dMaster.json?251024')
        .then(response => {
            if (!response.ok) throw Error(response.statusText)
            return response.json()
        })
        .then(json => {
            l2dmaster = json
            setupGameSelect(l2dmaster)
        })
        .catch(error => {
            console.log('failed while loading live2dMaster.json.')
        })

    l2dviewer = new l2dViewer(document.getElementById('viewer-place'))

    document.getElementById('addL2DModelBtn').onclick = async () => {
        let gameValue = document.getElementById('gameSelect').value
        let charValue = document.getElementById('characterSelect').value
        let costValue = document.getElementById('costumeSelect').value

        if (!gameValue || !charValue || !costValue) return

        let gameData = l2dmaster.Master.find(game => game.gameId == gameValue)
        let fulldata = gameData.character.find(char => char.charId == charValue)
        let costdata = fulldata.live2d.find(cost => cost.costumeId == costValue)

        document.getElementById('characterSelect').selectedIndex = 0
        document.getElementById('costumeSelect').innerHTML = ''

        if (l2dviewer.isModelInList(`${fulldata.charName}_${costdata.costumeName}`)) return

        let M = new HeroModel()
        await M.create(costdata.path)
        M.setName(fulldata.charName, costdata.costumeName)
        l2dviewer.addModel(M)

        let modelsList = document.getElementById('ModelsList')

        let infoblock = document.createElement("div")
        infoblock.className = 'modelInfoBlock'
        infoblock.innerHTML = `<h3 class="ModelName">${fulldata.charName}</h3>
                               <h5 class="CostumeName">【${costdata.costumeName}】</h5>`

        let settingBtn = document.createElement("button")
        settingBtn.className = "model-setting-btn"
        settingBtn.innerHTML = `<i class="fa-solid fa-ellipsis"></i>`
        settingBtn.onclick = () => {
            toggleTabContainer('ModelSetting')
            setupModelSetting(l2dviewer.findModel(`${fulldata.charName}_${costdata.costumeName}`))
        }
        infoblock.append(settingBtn)

        let removeBtn = document.createElement("button")
        removeBtn.className = "model-remove-btn"
        removeBtn.innerHTML = `<i class="fa-solid fa-xmark"></i>`
        removeBtn.onclick = () => {
            infoblock.remove()
            l2dviewer.removeModel(`${fulldata.charName}_${costdata.costumeName}`)
        }
        infoblock.append(removeBtn)

        modelsList.append(infoblock)
    }

    document.getElementById("colorPicker").onchange = function (e) {
        l2dviewer.setBGColor(String(this.value).replace(/#/, '0x'))
    }

    Array.from(document.getElementsByClassName('collapsible')).forEach(x => {
        x.addEventListener('click', function () {
            this.classList.toggle("active")
            let content = this.nextElementSibling
            if (content.style.display === "block") {
                content.style.display = "none"
            } else {
                content.style.display = "block"
            }
        })
    })
})